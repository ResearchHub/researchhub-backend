import logging
from datetime import datetime

from django.utils import timezone

from research_ai.constants import VALID_EMAIL_TEMPLATE_KEYS
from research_ai.models import ExpertSearch, GeneratedEmail, SearchExpert
from research_ai.services.email_generator_service import generate_expert_email
from research_ai.services.email_sending_service import send_plain_email
from research_ai.services.expert_finder_service import ExpertFinderService
from research_ai.services.expert_persist import mark_expert_last_email_sent_at
from research_ai.services.rfp_email_context import resolve_expert_from_search
from researchhub.celery import app
from user.models import User
from utils import sentry

logger = logging.getLogger(__name__)


def _resolve_excluded_expert_ids_from_search_ids(search_ids: list[int]) -> list[int]:
    """
    Union of expert PKs linked to the given ExpertSearch rows via SearchExpert.
    """
    if not search_ids:
        return []
    return list(
        SearchExpert.objects.filter(expert_search_id__in=search_ids)
        .values_list("expert_id", flat=True)
        .distinct()
    )


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


def _fail_expert_search(
    expert_search_id: int,
    *,
    error_message: str,
    current_step: str,
    processing_time: float | None,
    completed_at: datetime,
    llm_model: str = "",
) -> None:
    """Terminal FAILED state: clear links, reports, and denormalized counts."""
    SearchExpert.objects.filter(expert_search_id=expert_search_id).delete()
    ExpertSearch.objects.filter(id=expert_search_id).update(
        status=ExpertSearch.Status.FAILED,
        progress=0,
        current_step=current_step[:512],
        expert_count=0,
        report_pdf_url="",
        report_csv_url="",
        processing_time=processing_time,
        completed_at=completed_at,
        llm_model=(llm_model or "")[:128],
        error_message=(error_message or "")[:10000],
    )


@app.task(bind=True)
def process_expert_search_task(
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

    def progress_callback(sid: str, percent: int, message: str):
        status = (
            ExpertSearch.Status.COMPLETED
            if percent == 100
            else ExpertSearch.Status.PROCESSING
        )
        _update_search_progress(sid, percent, message, status=status)
        try:
            self.update_state(
                state="PROGRESS", meta={"progress": percent, "status": message}
            )
        except Exception:
            pass

    try:
        start_time = timezone.now()
        logger.info("Starting expert finder for search_id=%s", search_id)
        _update_search_progress(
            search_id,
            5,
            "Initializing expert search...",
            status=ExpertSearch.Status.PROCESSING,
        )

        service = ExpertFinderService()

        raw_sid = (
            ExpertSearch.objects.filter(pk=int(search_id))
            .values_list("excluded_search_ids", flat=True)
            .first()
        ) or []
        sid_list = [int(x) for x in raw_sid if x is not None]
        excluded_expert_ids = _resolve_excluded_expert_ids_from_search_ids(sid_list)

        result = service.process_expert_search(
            search_id=search_id,
            query=query,
            config=config,
            excluded_expert_ids=excluded_expert_ids,
            is_pdf=is_pdf,
            additional_context=additional_context,
            progress_callback=progress_callback,
        )

        end_time = timezone.now()
        processing_time = (end_time - start_time).total_seconds()

        if result.get("status") == ExpertSearch.Status.FAILED:
            error_message = (result.get("error_message") or "")[:10000]
            _fail_expert_search(
                int(search_id),
                error_message=error_message,
                current_step=result.get("current_step") or "No expert table returned",
                processing_time=processing_time,
                completed_at=end_time,
                llm_model=result.get("llm_model", "") or "",
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
        stored_count = int(result.get("expert_count") or 0)
        ExpertSearch.objects.filter(id=int(search_id)).update(
            status=ExpertSearch.Status.COMPLETED,
            progress=100,
            current_step="Expert search completed!",
            expert_count=stored_count,
            report_pdf_url=report_urls.get("pdf", ""),
            report_csv_url=report_urls.get("csv", ""),
            processing_time=processing_time,
            completed_at=end_time,
            llm_model=result.get("llm_model", ""),
        )

        logger.info(
            "Expert finder completed for search_id=%s, experts=%s, time=%.2fs",
            search_id,
            stored_count,
            processing_time,
        )
        return result

    except Exception as e:
        logger.exception("Expert finder failed for search_id=%s: %s", search_id, e)
        error_message = str(e)
        end_time = timezone.now()
        processing_time = (end_time - start_time).total_seconds()
        _update_search_progress(
            search_id,
            0,
            f"Processing failed: {error_message}",
            status=ExpertSearch.Status.FAILED,
        )
        _fail_expert_search(
            int(search_id),
            error_message=error_message,
            current_step=f"Processing failed: {error_message}",
            processing_time=processing_time,
            completed_at=end_time,
            llm_model="",
        )
        return {
            "search_id": search_id,
            "status": ExpertSearch.Status.FAILED,
            "error_message": error_message[:10000],
            "expert_count": 0,
            "report_urls": {},
            "llm_model": "",
        }


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
        resolved_expert = resolve_expert_from_search(
            rec.expert_search, rec.expert_email
        )
        if not resolved_expert:
            resolved_expert = {
                "name": rec.expert_name or "",
                "honorific": "",
                "first_name": "",
                "middle_name": "",
                "last_name": "",
                "academic_title": rec.expert_title or "",
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
    Process placeholder GeneratedEmail rows: generate subject/body, set status draft.

    Placeholders use status=processing; success -> draft, failure -> failed.
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
            mark_expert_last_email_sent_at(rec.expert_email)
            sent += 1
        except Exception as e:
            logger.exception("Send to expert failed id=%s: %s", rec.id, e)
            GeneratedEmail.objects.filter(id=rec.id).update(
                status=GeneratedEmail.Status.SEND_FAILED,
                updated_date=timezone.now(),
            )
            failed += 1
    return {"sent": sent, "failed": failed}
