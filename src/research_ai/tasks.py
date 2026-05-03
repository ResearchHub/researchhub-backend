import logging
from copy import deepcopy
from functools import partial

from django.conf import settings
from django.utils import timezone

from research_ai.constants import VALID_EMAIL_TEMPLATE_KEYS
from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.services.email_generator_service import generate_expert_email
from research_ai.services.email_sending_service import send_plain_email
from research_ai.services.expert_finder_service import ExpertFinderService
from research_ai.services.expert_finder_v2 import run_v2_expert_search
from researchhub.celery import app
from user.models import User
from utils import sentry

logger = logging.getLogger(__name__)

NON_PROD_EMAIL_SUFFIX = "_test"


def _maybe_obfuscate_expert_emails_for_non_production(experts: list) -> list:
    """
    In non-production (and not TESTING), mangle each expert's email
    (e.g. user@domain.com -> user_test@domain.com) so we don't accidentally
    send to real addresses from dev/staging.
    """
    if settings.PRODUCTION or settings.TESTING or not experts:
        return experts
    result = []
    for e in experts:
        copy = deepcopy(e)
        email = (copy.get("email") or "").strip()
        if email and "@" in email:
            local, _, domain = email.partition("@")
            copy["email"] = f"{local}{NON_PROD_EMAIL_SUFFIX}@{domain}"
        result.append(copy)
    return result


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
    """Update DB and Celery meta for expert search progress (v1 / v2)."""
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


def _resolve_v2_task_inputs(
    search_id: str,
    excluded_search_ids: list | None,
    additional_context: str | None,
) -> tuple[ExpertSearch | None, list[int], str | None]:
    """
    Load ExpertSearch and derive excluded-search ids + context for v2.

    Returns ``(None, [], None)`` when the search row is missing.
    """
    try:
        es = ExpertSearch.objects.get(id=int(search_id))
    except ExpertSearch.DoesNotExist:
        logger.warning(
            "run_expert_finder_search_v2: ExpertSearch %s not found", search_id
        )
        return None, [], None

    merged = (
        excluded_search_ids
        if excluded_search_ids is not None
        else (es.excluded_search_ids or [])
    )
    norm: list[int] = []
    for x in merged or []:
        try:
            norm.append(int(x))
        except (TypeError, ValueError):
            continue

    if additional_context is not None:
        ctx: str | None = additional_context
    else:
        stripped = (es.additional_context or "").strip()
        ctx = stripped or None

    return es, norm, ctx


def _finalize_v2_expert_search_in_db(
    search_id: str,
    result: dict,
    end_time,
    processing_time: float,
) -> bool:
    """
    Persist v2 result to ExpertSearch. Returns True if the run failed (soft failure).
    """
    sid = int(search_id)
    if result.get("status") == ExpertSearch.Status.FAILED:
        error_message = (result.get("error_message") or "")[:10000]
        ExpertSearch.objects.filter(id=sid).update(
            status=ExpertSearch.Status.FAILED,
            progress=0,
            current_step=(result.get("current_step") or "V2 expert search failed")[
                :512
            ],
            expert_results=[],
            expert_count=0,
            report_pdf_url="",
            report_csv_url="",
            processing_time=processing_time,
            completed_at=end_time,
            llm_model=result.get("llm_model", ""),
            error_message=error_message,
        )
        snippet = error_message[:200] if len(error_message) > 200 else error_message
        logger.warning(
            "V2 expert finder failed for search_id=%s: %s", search_id, snippet
        )
        return True

    ExpertSearch.objects.filter(id=sid).update(
        status=ExpertSearch.Status.COMPLETED,
        progress=100,
        current_step="Expert search completed!",
        expert_results=[],
        expert_count=result.get("expert_count", 0),
        report_pdf_url=result.get("report_urls", {}).get("pdf", ""),
        report_csv_url=result.get("report_urls", {}).get("csv", ""),
        processing_time=processing_time,
        completed_at=end_time,
        llm_model=result.get("llm_model", ""),
    )
    return False


@app.task(bind=True)
def process_expert_search_task(
    self,
    search_id: str,
    query: str,
    config: dict,
    *,
    excluded_expert_names: list | None = None,
    is_pdf: bool = False,
    additional_context: str | None = None,
):
    """
    Background task to process an expert search.

    Args:
        search_id: ExpertSearch id (string of integer).
        query: Research description or document text.
        config: Dict with expert_count, expertise_level, region, state, gender.
        excluded_expert_names: Optional list of expert names to exclude.
        is_pdf: True if query was extracted from PDF.
        additional_context: Optional user notes to steer the model alongside query.
    """

    progress_callback = partial(_expert_search_task_progress_callback, self)

    try:
        logger.info("Starting expert finder for search_id=%s", search_id)
        _update_search_progress(
            search_id,
            5,
            "Initializing expert search...",
            status=ExpertSearch.Status.PROCESSING,
        )

        service = ExpertFinderService()
        start_time = timezone.now()

        result = service.process_expert_search(
            search_id=search_id,
            query=query,
            config=config,
            excluded_expert_names=excluded_expert_names or [],
            is_pdf=is_pdf,
            additional_context=additional_context,
            progress_callback=progress_callback,
        )

        end_time = timezone.now()
        processing_time = (end_time - start_time).total_seconds()

        if result.get("status") == ExpertSearch.Status.FAILED:
            error_message = (result.get("error_message") or "")[:10000]
            ExpertSearch.objects.filter(id=int(search_id)).update(
                status=ExpertSearch.Status.FAILED,
                progress=0,
                current_step=(result.get("current_step") or "No expert table returned")[
                    :512
                ],
                expert_results=[],
                expert_count=0,
                report_pdf_url="",
                report_csv_url="",
                processing_time=processing_time,
                completed_at=end_time,
                llm_model=result.get("llm_model", ""),
                error_message=error_message,
            )
            logger.warning(
                "Expert finder failed for search_id=%s (no table parsed): %s",
                search_id,
                (
                    error_message[:200] + "..."
                    if len(error_message) > 200
                    else error_message
                ),
            )
            return result
        report_urls = result.get("report_urls", {})
        experts = _maybe_obfuscate_expert_emails_for_non_production(
            result.get("experts", [])
        )
        ExpertSearch.objects.filter(id=int(search_id)).update(
            status=ExpertSearch.Status.COMPLETED,
            progress=100,
            current_step="Expert search completed!",
            expert_results=experts,
            expert_count=result.get("expert_count", 0),
            report_pdf_url=report_urls.get("pdf", ""),
            report_csv_url=report_urls.get("csv", ""),
            processing_time=processing_time,
            completed_at=end_time,
            llm_model=result.get("llm_model", ""),
        )

        logger.info(
            "Expert finder completed for search_id=%s, experts=%s, time=%.2fs",
            search_id,
            result.get("expert_count", 0),
            processing_time,
        )
        return result

    except Exception as e:
        logger.exception("Expert finder failed for search_id=%s: %s", search_id, e)
        error_message = str(e)
        _update_search_progress(
            search_id,
            0,
            f"Processing failed: {error_message}",
            status=ExpertSearch.Status.FAILED,
        )
        ExpertSearch.objects.filter(id=int(search_id)).update(
            status=ExpertSearch.Status.FAILED,
            error_message=error_message[:10000],
        )
        raise


@app.task(bind=True)
def run_expert_finder_search_v2(
    self,
    search_id: str,
    query: str,
    config: dict,
    *,
    excluded_search_ids: list | None = None,
    is_pdf: bool = False,
    additional_context: str | None = None,
):
    """
    Background task to process an expert search.

    Args:
        search_id: ExpertSearch id (string of integer).
        query: Research description or document text.
        config: Dict with expert_count, expertise_level, region, state, gender.
        excluded_search_ids: Optional list of expert search ids to exclude.
        is_pdf: True if query was extracted from PDF.
        additional_context: Optional user notes to steer the model alongside query.
    """

    progress_callback = partial(_expert_search_task_progress_callback, self)

    es, norm_search_ids, additional_context = _resolve_v2_task_inputs(
        search_id, excluded_search_ids, additional_context
    )
    if es is None:
        return {"status": "not_found", "search_id": search_id}

    try:
        logger.info("Starting v2 expert finder for search_id=%s", search_id)
        _update_search_progress(
            search_id,
            5,
            "Initializing expert search (v2)...",
            status=ExpertSearch.Status.PROCESSING,
        )
        start_time = timezone.now()
        result = run_v2_expert_search(
            search_id=search_id,
            query=query,
            config=config,
            excluded_search_ids=norm_search_ids,
            is_pdf=is_pdf,
            additional_context=additional_context,
            progress_callback=progress_callback,
        )
        end_time = timezone.now()
        processing_time = (end_time - start_time).total_seconds()
        failed = _finalize_v2_expert_search_in_db(
            search_id, result, end_time, processing_time
        )
        if failed:
            return result
        logger.info(
            "V2 expert finder completed search_id=%s experts=%s time=%.2fs",
            search_id,
            result.get("expert_count", 0),
            processing_time,
        )
        return result
    except Exception as e:
        logger.exception("V2 expert finder failed for search_id=%s: %s", search_id, e)
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


def _process_one_bulk_email(
    email_id: int,
    template_key: str | None,
    custom_use_case: str | None,
    user,
    template_id: int | None,
) -> tuple[int, int]:
    """
    Generate email for one placeholder and update record. Returns (success_delta, failed_delta).
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
        resolved_expert = {
            "name": rec.expert_name or "",
            "title": rec.expert_title or "",
            "affiliation": rec.expert_affiliation or "",
            "expertise": rec.expertise or "",
            "email": rec.expert_email or "",
            "notes": rec.notes or "",
        }
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
        sentry.log_error(e, message=f"Bulk generate error for email id={email_id}")
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
    Process placeholder GeneratedEmail rows: generate subject/body and set status to draft.
    Placeholders have status=processing; on success set to draft, on failure set to failed.
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
    except Exception as e:
        logger.exception("Bulk generate task failed: %s", e)
        sentry.log_error(e, message="Bulk generate emails task failed")
        _mark_generated_emails_failed(generated_email_ids)
        raise


@app.task(bind=True)
def send_queued_emails_task(
    self,
    generated_email_ids: list[int],
    reply_to: str | None = None,
    cc: list[str] | None = None,
    from_email: str | None = None,
):
    """
    Send generated emails that are in SENDING status. Updates each to SENT on
    success or SEND_FAILED on failure.
    """

    cc_list = list(cc or [])
    reply_to_stripped = (reply_to or "").strip() or None
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
                reply_to=reply_to_stripped,
                cc=cc_list if cc_list else None,
                from_email=from_email,
            )
            GeneratedEmail.objects.filter(id=rec.id).update(
                status=GeneratedEmail.Status.SENT,
                ses_message_id=ses_message_id or "",
                updated_date=timezone.now(),
            )
            sent += 1
        except Exception as e:
            logger.exception("Send to expert failed id=%s: %s", rec.id, e)
            GeneratedEmail.objects.filter(id=rec.id).update(
                status=GeneratedEmail.Status.SEND_FAILED,
                updated_date=timezone.now(),
            )
            failed += 1
    return {"sent": sent, "failed": failed}
