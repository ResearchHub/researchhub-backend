import logging
from copy import deepcopy
from datetime import datetime

from django.conf import settings

from research_ai.constants import VALID_EMAIL_TEMPLATE_KEYS
from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.services.email_generator_service import generate_expert_email
from research_ai.services.expert_finder_service import ExpertFinderService
from researchhub.celery import app
from user.models import User

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


@app.task(bind=True)
def process_expert_search_task(
    self,
    search_id: str,
    query: str,
    config: dict,
    *,
    excluded_expert_names: list | None = None,
    is_pdf: bool = False,
):
    """
    Background task to process an expert search.

    Args:
        search_id: ExpertSearch id (string of integer).
        query: Research description or document text.
        config: Dict with expert_count, expertise_level, region, state, gender.
        excluded_expert_names: Optional list of expert names to exclude.
        is_pdf: True if query was extracted from PDF.
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
        logger.info("Starting expert finder for search_id=%s", search_id)
        _update_search_progress(
            search_id,
            5,
            "Initializing expert search...",
            status=ExpertSearch.Status.PROCESSING,
        )

        service = ExpertFinderService()
        start_time = datetime.utcnow()

        result = service.process_expert_search(
            search_id=search_id,
            query=query,
            config=config,
            excluded_expert_names=excluded_expert_names or [],
            is_pdf=is_pdf,
            progress_callback=progress_callback,
        )

        end_time = datetime.utcnow()
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

    def _normalize_template(template: str) -> tuple[str, str | None]:
        template = (template or "").strip()
        if template.startswith("custom:"):
            return "custom", template[7:].strip() or None
        if template in VALID_EMAIL_TEMPLATE_KEYS:
            return template, None
        return "custom", template or None

    if not generated_email_ids:
        return {"processed": 0}

    try:
        first = (
            GeneratedEmail.objects.filter(
                id__in=generated_email_ids,
                status=GeneratedEmail.Status.PROCESSING,
            )
            .select_related("expert_search", "created_by")
            .first()
        )
        if not first:
            logger.warning(
                "No processing placeholders found for ids=%s", generated_email_ids
            )
            return {"processed": 0}

        created_by = first.created_by
        template_key, custom_use_case = _normalize_template(first.template or "")

        user = created_by
        if template_id and created_by_id:
            try:
                user = User.objects.get(id=created_by_id)
            except User.DoesNotExist:
                pass

        success = 0
        failed = 0
        for email_id in generated_email_ids:
            try:
                rec = (
                    GeneratedEmail.objects.filter(
                        id=email_id,
                        status=GeneratedEmail.Status.PROCESSING,
                    )
                    .select_related("expert_search")
                    .first()
                )
                if not rec:
                    continue
                subject = ""
                body = ""
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
                except Exception as e:
                    logger.warning(
                        "Bulk generate failed for email id=%s: %s", email_id, e
                    )
                    rec.status = GeneratedEmail.Status.FAILED
                    rec.save(update_fields=["status", "updated_date"])
                    failed += 1
                    continue
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
                success += 1
            except Exception as e:
                logger.exception("Bulk generate error for email id=%s: %s", email_id, e)
                try:
                    GeneratedEmail.objects.filter(id=email_id).update(
                        status=GeneratedEmail.Status.FAILED
                    )
                except Exception:
                    pass
                failed += 1

        return {"processed": success + failed, "success": success, "failed": failed}
    except Exception as e:
        logger.exception("Bulk generate task failed: %s", e)
        for email_id in generated_email_ids:
            try:
                GeneratedEmail.objects.filter(id=email_id).update(
                    status=GeneratedEmail.Status.FAILED
                )
            except Exception:
                pass
        raise
