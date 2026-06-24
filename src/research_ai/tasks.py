import logging
from functools import partial

from django.utils import timezone

from research_ai.constants import VALID_EMAIL_TEMPLATE_KEYS
from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.services import expert_finder_service as expert_finder_service_mod
from research_ai.services.email_generator_service import generate_expert_email
from research_ai.services.email_sending_service import send_plain_email
from research_ai.services.expert_display import ExpertDisplay
from research_ai.services.expert_persist import ExpertPersist
from research_ai.services.invited_experts_service import (
    grant_invited_expert_access_for_send,
    link_experts_for_new_user,
)
from research_ai.services.rfp_email_context import get_expert_for_search_by_email
from researchhub.celery import app
from user.models import User

logger = logging.getLogger(__name__)


def _update_search_progress(
    search_id: str,
    percent: int,
    message: str,
    status: str = ExpertSearch.Status.PROCESSING,
):
    """Update ExpertSearch progress in DB (for use from Celery)."""

    try:
        ExpertSearch.objects.filter(id=int(search_id)).update(
            progress=percent,
            current_step=message[:512],
            status=status,
        )
    except Exception as e:
        logger.warning("Failed to update expert search progress: %s", e)


def _expert_search_task_progress_callback(
    task_self, sid: str, percent: int, message: str
):
    """Update DB and Celery meta for expert search progress."""
    status = (
        ExpertSearch.Status.COMPLETED
        if percent == 100
        else ExpertSearch.Status.PROCESSING
    )
    _update_search_progress(sid, percent, message, status=status)
    try:
        task_self.update_state(
            state="PROGRESS", meta={"progress": percent, "status": message}
        )
    except Exception:
        pass


def _resolve_expert_finder_task_inputs(
    search_id: str,
    additional_context: str | None,
) -> tuple[ExpertSearch | None, str | None]:
    """
    Load ExpertSearch and resolve additional_context.

    Returns ``(None, None)`` when the search row is missing.
    """
    try:
        es = ExpertSearch.objects.get(id=int(search_id))
    except ExpertSearch.DoesNotExist:
        logger.warning("run_expert_finder_search: ExpertSearch %s not found", search_id)
        return None, None

    if additional_context is not None:
        ctx: str | None = additional_context
    else:
        stripped = (es.additional_context or "").strip()
        ctx = stripped or None

    return es, ctx


def _finalize_expert_search_in_db(
    search_id: str,
    result: dict,
    end_time,
    processing_time: float,
) -> bool:
    """
    Persist result to ExpertSearch. Returns True if the run failed (soft failure).
    """
    sid = int(search_id)
    if result.get("status") == ExpertSearch.Status.FAILED:
        error_message = (result.get("error_message") or "")[:10000]
        ExpertSearch.objects.filter(id=sid).update(
            status=ExpertSearch.Status.FAILED,
            progress=0,
            current_step=(result.get("current_step") or "Expert search failed")[:512],
            expert_count=0,
            report_pdf_url="",
            report_csv_url="",
            processing_time=processing_time,
            completed_at=end_time,
            llm_model=result.get("llm_model", ""),
            error_message=error_message,
        )
        snippet = error_message[:200] if len(error_message) > 200 else error_message
        current_step = (result.get("current_step") or "Expert search failed")[:512]
        logger.warning(
            "Expert finder failed for search_id=%s step=%s: %s",
            search_id,
            current_step,
            snippet,
        )
        return True

    ExpertSearch.objects.filter(id=sid).update(
        status=ExpertSearch.Status.COMPLETED,
        progress=100,
        current_step="Expert search completed!",
        expert_count=result.get("expert_count", 0),
        report_pdf_url=result.get("report_urls", {}).get("pdf", ""),
        report_csv_url=result.get("report_urls", {}).get("csv", ""),
        processing_time=processing_time,
        completed_at=end_time,
        llm_model=result.get("llm_model", ""),
    )
    return False


@app.task
def link_experts_after_signup(
    normalized_email: str,
    user_id: int,
) -> None:
    """
    For a newly created user: link ``Expert`` rows (``registered_user``) when outreach
    qualifies.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning(
            "link_experts_after_signup: user_id=%s not found",
            user_id,
        )
        return
    link_experts_for_new_user(
        normalized_email=normalized_email,
        user=user,
    )


@app.task(bind=True)
def run_expert_finder_search(
    self,
    search_id: str,
    query: str,
    config: dict,
    *,
    is_pdf: bool = False,
    additional_context: str | None = None,
):
    """
    Background task to process an expert search.

    Args:
        search_id: ExpertSearch id (string of integer).
        query: Research description or document text.
        config: Dict with expert_count, expertise_level, region, state, gender.
        is_pdf: True if query was extracted from PDF.
        additional_context: Optional user notes to steer the model alongside query.
    """

    progress_callback = partial(_expert_search_task_progress_callback, self)

    es, additional_context = _resolve_expert_finder_task_inputs(
        search_id, additional_context
    )
    if es is None:
        return {"status": "not_found", "search_id": search_id}

    try:
        logger.info("Starting expert finder for search_id=%s", search_id)
        _update_search_progress(
            search_id,
            5,
            "Initializing expert search...",
            status=ExpertSearch.Status.PROCESSING,
        )
        start_time = timezone.now()
        result = expert_finder_service_mod.run_expert_finder_search(
            search_id=search_id,
            query=query,
            config=config,
            is_pdf=is_pdf,
            additional_context=additional_context,
            progress_callback=progress_callback,
        )
        end_time = timezone.now()
        processing_time = (end_time - start_time).total_seconds()
        failed = _finalize_expert_search_in_db(
            search_id, result, end_time, processing_time
        )
        if failed:
            return result
        logger.info(
            "Expert finder completed search_id=%s experts=%s time=%.2fs",
            search_id,
            result.get("expert_count", 0),
            processing_time,
        )
        return result
    except Exception as e:
        logger.exception(
            "Expert finder search task failed", extra={"search_id": search_id}
        )
        err = str(e)[:10000]
        _update_search_progress(
            search_id,
            0,
            f"Processing failed: {err}",
            status=ExpertSearch.Status.FAILED,
        )
        ExpertSearch.objects.filter(id=int(search_id)).update(
            status=ExpertSearch.Status.FAILED,
            error_message=err,
        )
        raise


def _normalize_template_for_bulk(template: str | None) -> tuple[str | None, str | None]:
    """Normalize stored GeneratedEmail.template to (template_key, custom_use_case)."""
    if template is None:
        return None, None
    template = template.strip()
    if not template:
        return "custom", None
    if template.startswith("custom:"):
        return "custom", template[7:].strip() or None
    if template in VALID_EMAIL_TEMPLATE_KEYS:
        return template, None
    return "custom", template or None


def _get_bulk_emails_task_context(
    generated_email_ids: list[int],
    template_id: int | None,
    created_by_id: int | None,
) -> tuple | None:
    """
    Resolve user and template params from the first processing placeholder.
    Returns (user, template_key, custom_use_case) or None if no placeholder found.
    """
    first = (
        GeneratedEmail.objects.filter(
            id__in=generated_email_ids,
            status=GeneratedEmail.Status.PROCESSING,
        )
        .select_related("expert_search", "created_by")
        .first()
    )
    if not first:
        return None
    user = first.created_by
    if template_id and created_by_id:
        try:
            user = User.objects.get(id=created_by_id)
        except User.DoesNotExist:
            pass
    template_key, custom_use_case = _normalize_template_for_bulk(first.template)
    return (user, template_key, custom_use_case)


def _resolved_expert_dict_for_bulk(rec: GeneratedEmail) -> dict:
    """
    Prefer live ``Expert`` on the search; fall back to denormalized ``GeneratedEmail``.
    """
    es = rec.expert_search
    if es and rec.expert_email:
        expert = get_expert_for_search_by_email(es, rec.expert_email)
        if expert is not None:
            return ExpertDisplay.email_generation_dict(expert)
    return {
        "name": rec.expert_name or "",
        "title": rec.expert_title or "",
        "affiliation": rec.expert_affiliation or "",
        "expertise": rec.expertise or "",
        "email": (rec.expert_email or "").strip(),
        "notes": rec.notes or "",
    }


def _process_one_bulk_email(
    email_id: int,
    template_key: str | None,
    custom_use_case: str | None,
    user,
    template_id: int | None,
) -> tuple[int, int]:
    """
    Generate email for one placeholder and update record.
    Returns (success_delta, failed_delta).
    """
    rec = (
        GeneratedEmail.objects.filter(
            id=email_id,
            status=GeneratedEmail.Status.PROCESSING,
        )
        .select_related("expert_search")
        .first()
    )
    if not rec:
        return 0, 0
    try:
        resolved_expert = _resolved_expert_dict_for_bulk(rec)
        subject, body = generate_expert_email(
            resolved_expert=resolved_expert,
            template=template_key,
            custom_use_case=custom_use_case,
            expert_search=rec.expert_search,
            template_id=template_id,
            user=user,
        )
        rec.email_subject = subject
        rec.email_body = body
        rec.status = GeneratedEmail.Status.DRAFT
        rec.save(
            update_fields=[
                "email_subject",
                "email_body",
                "status",
                "updated_date",
            ]
        )
        return 1, 0
    except Exception as e:
        logger.warning("Bulk generate failed for email id=%s: %s", email_id, e)
        try:
            rec.status = GeneratedEmail.Status.FAILED
            rec.save(update_fields=["status", "updated_date"])
        except Exception:
            GeneratedEmail.objects.filter(id=email_id).update(
                status=GeneratedEmail.Status.FAILED
            )
        return 0, 1


def _mark_generated_emails_failed(email_ids: list[int]) -> None:
    """Set all given GeneratedEmail rows to FAILED; swallow per-id errors."""
    for email_id in email_ids:
        try:
            GeneratedEmail.objects.filter(id=email_id).update(
                status=GeneratedEmail.Status.FAILED
            )
        except Exception:
            pass


@app.task(bind=True)
def process_bulk_generate_emails_task(
    self,
    generated_email_ids: list[int],
    *,
    template_id: int | None = None,
    created_by_id: int | None = None,
):
    """
    Process placeholder GeneratedEmail rows: generate subject/body and set status to
    draft.
    Placeholders have status=processing; on success set to draft, on failure set to
    failed.
    """
    if not generated_email_ids:
        return {"processed": 0}

    try:
        context = _get_bulk_emails_task_context(
            generated_email_ids, template_id, created_by_id
        )
        if context is None:
            logger.warning(
                "No processing placeholders found for ids=%s", generated_email_ids
            )
            return {"processed": 0}

        user, template_key, custom_use_case = context
        success = 0
        failed = 0
        for email_id in generated_email_ids:
            s, f = _process_one_bulk_email(
                email_id, template_key, custom_use_case, user, template_id
            )
            success += s
            failed += f
        return {"processed": success + failed, "success": success, "failed": failed}
    except Exception:
        logger.exception("Bulk generate task failed")
        _mark_generated_emails_failed(generated_email_ids)
        raise


@app.task(bind=True)
def send_queued_emails_task(
    self,
    generated_email_ids: list[int],
    reply_to: list[str] | None = None,
    cc: list[str] | None = None,
    from_email: str | None = None,
):
    """
    Send generated emails that are in SENDING status. Updates each to SENT on
    success or SEND_FAILED on failure.
    """

    cc_list = list(cc or [])
    reply_to_list = list(reply_to or [])
    qs = GeneratedEmail.objects.filter(
        id__in=generated_email_ids,
        status=GeneratedEmail.Status.SENDING,
    ).order_by("id")
    sent = 0
    failed = 0
    for rec in qs:
        if not (rec.expert_email or "").strip():
            rec.status = GeneratedEmail.Status.SEND_FAILED
            rec.save(update_fields=["status", "updated_date"])
            failed += 1
            continue
        try:
            ses_message_id = send_plain_email(
                rec.expert_email,
                rec.email_subject,
                rec.email_body,
                reply_to=reply_to_list or None,
                cc=cc_list if cc_list else None,
                from_email=from_email,
            )
            GeneratedEmail.objects.filter(id=rec.id).update(
                status=GeneratedEmail.Status.SENT,
                ses_message_id=ses_message_id or "",
                updated_date=timezone.now(),
            )
            ExpertPersist.mark_last_email_sent_at(rec.expert_email or "")
            try:
                grant_invited_expert_access_for_send(generated_email=rec)
            except Exception:
                # Don't let an access-grant failure mask a successful send.
                logger.exception("Grant access on send failed id=%s", rec.id)
            sent += 1
        except Exception:
            logger.exception("Send to expert failed id=%s", rec.id)
            GeneratedEmail.objects.filter(id=rec.id).update(
                status=GeneratedEmail.Status.SEND_FAILED,
                updated_date=timezone.now(),
            )
            failed += 1
    return {"sent": sent, "failed": failed}
