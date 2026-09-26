import logging
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from research_ai.constants import (
    EXPERT_FINDER_DEFAULT_STATE,
    MAX_PDF_SIZE_BYTES,
    ExpertiseLevel,
    Region,
)
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.agent import generator_model_ref
from research_ai.services.agent.errors import BudgetExceededError
from research_ai.services.expert_finder.agent_runner import run_expert_finder_agent
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.expert_finder.persist import ExpertPersist
from research_ai.services.expert_finder.progress import ProgressService, TaskType
from research_ai.services.expert_finder.report_generator import (
    expert_to_report_row,
    generate_csv_file,
    generate_pdf_report,
    upload_report_to_storage,
)
from research_ai.services.expert_finder.source_enrichment import SourceEnrichmentService
from research_ai.services.pdf_text import (
    extract_text_from_pdf_bytes as _extract_text_from_pdf_bytes,
)
from research_ai.services.pdf_text import (
    get_paper_pdf_bytes as _get_paper_pdf_bytes,
)
from researchhub_document.related_models.constants.document_type import PAPER

logger = logging.getLogger(__name__)

NON_PROD_EMAIL_SUFFIX = "_test"


def _maybe_obfuscate_expert_emails_for_non_production(
    experts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    In non-production (and not TESTING), mangle each expert's email
    (e.g. user@domain.com -> user_test@domain.com) so we don't accidentally
    use real addresses from dev/staging in the database.
    """
    if settings.PRODUCTION or settings.TESTING or not experts:
        return experts
    result: list[dict[str, Any]] = []
    for row in experts:
        copy = deepcopy(row)
        email = (copy.get("email") or "").strip()
        if email and "@" in email:
            local, _, domain = email.partition("@")
            copy["email"] = f"{local}{NON_PROD_EMAIL_SUFFIX}@{domain}"
        result.append(copy)
    return result


PDF_TOO_LARGE_MESSAGE = (
    "PDF is too large. Maximum size is 10 MB. "
    "Please use another input type (e.g. abstract)."
)
MAX_ERROR_MESSAGE_LENGTH = 10000

EXPERT_FILL_EXCLUDED_NAMES_CAP = 250

_DECEASED_ROW_REGEX = re.compile(
    r"(?i)(?:"
    r"\b(?:the\s+)?late\s+(?:dr\.?|prof\.?|professor)\b|"
    r"\bdeceased\b|"
    r"\bpassed\s+away\b|"
    r"\bin\s+memoriam\b|"
    r"\bposthumous(?:ly)?\b|"
    r"\brest\s+in\s+peace\b|"
    r"\(d\.\s*\d{4}\)|"
    r"\bd\.\s*\d{4}\b|"
    r"\bdied\s+(?:in|on)?\s*\d{4}\b"
    r")"
)


def get_document_content(unified_doc, input_type: str):
    """
    Extract content from UnifiedDocument for expert finder.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance.
        input_type: "full_content", "pdf", "custom_query", or "abstract" (required).

    Returns:
        tuple: (content_text, content_type) where content_type is one of
               "full_content", "pdf", "abstract".

    Raises:
        ValueError: If requested content is not available.
    """

    if unified_doc.document_type == PAPER:
        paper = unified_doc.paper

        if input_type == "abstract":
            if not paper.abstract:
                raise ValueError("Abstract is not available for this paper.")
            return (paper.abstract, "abstract")

        if input_type == "pdf":
            pdf_bytes = _get_paper_pdf_bytes(paper)
            if not pdf_bytes:
                raise ValueError("PDF is not available for this paper.")
            if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
                raise ValueError(PDF_TOO_LARGE_MESSAGE)
            text = _extract_text_from_pdf_bytes(pdf_bytes)
            return (text, "pdf")

        raise ValueError("Invalid input_type for paper. Use 'pdf' or 'abstract'.")

    post = unified_doc.posts.first()
    if not post:
        raise ValueError("Document has no post content")
    if getattr(post, "renderable_text", None):
        return (post.renderable_text, "full_content")
    try:
        full = post.get_full_markdown()
        if full:
            return (full, "full_content")
    except Exception:
        pass
    raise ValueError("Post has no content available")


def clear_expert_search_links(expert_search_id: int) -> None:
    SearchExpert.objects.filter(expert_search_id=expert_search_id).delete()


def load_experts_for_expert_search(expert_search_id: int) -> list[Expert]:
    qs = (
        SearchExpert.objects.filter(expert_search_id=expert_search_id)
        .select_related("expert")
        .order_by("position")
    )
    return [se.expert for se in qs]


def _names_and_emails_from_prior_document_searches(
    unified_document_id: int | None,
    *,
    exclude_search_id: int | None = None,
) -> tuple[list[str], set[str]]:
    if not unified_document_id:
        return [], set()
    out_names: list[str] = []
    out_emails: set[str] = set()
    qs = SearchExpert.objects.filter(
        expert_search__unified_document_id=unified_document_id,
    ).select_related("expert")
    if exclude_search_id is not None:
        qs = qs.exclude(expert_search_id=exclude_search_id)
    for se in qs:
        e = se.expert
        label = ExpertDisplay.personal_name_for(e)
        if label:
            out_names.append(label)
        em = (e.email or "").strip().lower()
        if em:
            out_emails.add(em)
    return out_names, out_emails


class ExpertFinderService:
    def __init__(self):
        self.progress_service = ProgressService()

    @staticmethod
    def _expert_row_suggests_deceased(row: dict[str, Any]) -> bool:
        name_bits = [
            row.get("honorific") or "",
            row.get("first_name") or "",
            row.get("middle_name") or "",
            row.get("last_name") or "",
            row.get("name_suffix") or "",
        ]
        name_blob = " ".join(str(x).strip() for x in name_bits if x and str(x).strip())
        parts = [
            name_blob,
            row.get("academic_title") or "",
            row.get("affiliation") or "",
            row.get("expertise") or "",
            row.get("notes") or "",
        ]
        blob = " ".join(p.strip() for p in parts if p and str(p).strip())
        if not blob:
            return False
        return _DECEASED_ROW_REGEX.search(blob) is not None

    @staticmethod
    def _dedupe_experts_by_normalized_email(
        experts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for e in experts:
            raw = (e.get("email") or "").strip()
            if not raw:
                continue
            try:
                EmailValidator()(raw)
            except ValidationError:
                continue
            key = raw.lower()
            if key in seen:
                continue
            seen.add(key)
            row = dict(e)
            row["email"] = key
            out.append(row)
        return out

    @staticmethod
    def _capped_excluded_names(names: list[str]) -> list[str]:
        cleaned = [n for n in names if n]
        if len(cleaned) <= EXPERT_FILL_EXCLUDED_NAMES_CAP:
            return cleaned
        logger.warning(
            "Expert finder: exclusion list length %s exceeds cap %s; truncating",
            len(cleaned),
            EXPERT_FILL_EXCLUDED_NAMES_CAP,
        )
        return cleaned[:EXPERT_FILL_EXCLUDED_NAMES_CAP]

    def process_expert_search(
        self,
        search_id: str,
        query: str,
        config: dict[str, Any],
        *,
        is_pdf: bool = False,  # noqa: ARG002 — kept for Celery/task API compat
        additional_context: str | None = None,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> dict[str, Any]:
        expert_search_id = int(search_id)
        try:
            unified_document_id = (
                ExpertSearch.objects.only("unified_document_id")
                .get(id=expert_search_id)
                .unified_document_id
            )
        except ExpertSearch.DoesNotExist:
            unified_document_id = None
        progress_service = self.progress_service
        llm_model = generator_model_ref()

        def publish_progress(
            message: str,
            percent: int,
            status: str = ExpertSearch.Status.PROCESSING,
        ):
            status_val = status.value if hasattr(status, "value") else status
            progress_service.publish_progress_sync(
                TaskType.EXPERTS,
                search_id,
                {
                    "status": status_val,
                    "progress": percent,
                    "currentStep": message,
                    "type": (
                        "progress"
                        if status_val == ExpertSearch.Status.PROCESSING
                        else status_val
                    ),
                },
            )
            if progress_callback:
                progress_callback(search_id, percent, message)

        def fail_return(
            msg: str,
            *,
            current_step: str,
            store_full_response_error: str | None = None,
            exc: BaseException | None = None,
            extra: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "search_id": search_id,
                "current_step": current_step,
            }
            if extra:
                payload.update(extra)
            logger.error(
                "Expert finder failed: %s payload=%s",
                current_step,
                payload,
                exc_info=(exc if exc is not None else RuntimeError(current_step)),
                extra=extra,
            )
            clear_expert_search_links(expert_search_id)
            err = (store_full_response_error or msg)[:MAX_ERROR_MESSAGE_LENGTH]
            publish_progress(msg, 0, status=ExpertSearch.Status.FAILED)
            return {
                "search_id": search_id,
                "status": ExpertSearch.Status.FAILED,
                "query": query,
                "config": config,
                "experts": [],
                "report_urls": {},
                "expert_count": 0,
                "llm_model": llm_model,
                "error_message": err,
                "current_step": current_step[:512],
            }

        data_persisted = False
        try:
            search_id_names, search_id_emails = (
                _names_and_emails_from_prior_document_searches(
                    unified_document_id,
                    exclude_search_id=expert_search_id,
                )
            )
            expert_count = int(config.get("expert_count", 10) or 10)
            target_expert_count = max(0, expert_count)
            expertise_level_raw = config.get(
                "expertise_level", [ExpertiseLevel.ALL_LEVELS]
            )
            if isinstance(expertise_level_raw, str):
                expertise_level: list[str] = (
                    [expertise_level_raw]
                    if expertise_level_raw
                    else [ExpertiseLevel.ALL_LEVELS]
                )
            elif expertise_level_raw:
                expertise_level = []
                for x in expertise_level_raw:
                    if isinstance(x, str):
                        expertise_level.append(x)
                    elif isinstance(x, list):
                        expertise_level.extend(y for y in x if isinstance(y, str))
            else:
                expertise_level = [ExpertiseLevel.ALL_LEVELS]
            region_filter = config.get("region", Region.ALL_REGIONS)
            state_filter = config.get("state", EXPERT_FINDER_DEFAULT_STATE)
            excluded_names = self._capped_excluded_names(
                [n for n in search_id_names if n]
            )

            publish_progress("Finding experts via agent search...", 28)
            try:
                agent_result = run_expert_finder_agent(
                    query=query,
                    expert_count=target_expert_count,
                    expertise_level=expertise_level,
                    region_filter=region_filter,
                    state_filter=state_filter,
                    excluded_expert_names=excluded_names,
                    additional_context=additional_context,
                )
            except BudgetExceededError:
                raise
            except Exception as e:
                return fail_return(
                    f"Expert agent search failed: {e}"[:2000],
                    current_step="Agent search failed",
                    exc=e,
                )

            publish_progress("Validating grounded expert recommendations...", 58)
            batch = list(agent_result.get("experts") or [])
            n_before = len(batch)
            kept: list[dict[str, Any]] = []
            for row in batch:
                em = (row.get("email") or "").strip().lower()
                if not em:
                    continue
                if search_id_emails and em in search_id_emails:
                    continue
                kept.append(row)
            all_filtered_by_exclusion = bool(
                search_id_emails and n_before > 0 and not kept
            )

            experts_rows = self._dedupe_experts_by_normalized_email(
                [r for r in kept if not self._expert_row_suggests_deceased(r)]
            )[:target_expert_count]

            if len(experts_rows) == 0:
                agent_errors = agent_result.get("errors") or []
                if all_filtered_by_exclusion:
                    umsg = (
                        "Every recommendation matched an email from a prior expert "
                        "search on this document. Try broadening criteria."
                    )
                    return fail_return(umsg, current_step="All experts excluded")

                umsg = (
                    "No expert recommendations were returned. The agent did not "
                    "yield at least one grounded expert with a validated email."
                )
                if agent_errors:
                    detail = "; ".join(str(e) for e in agent_errors)
                    umsg = (
                        umsg + " Agent details:\n\n" + detail[:MAX_ERROR_MESSAGE_LENGTH]
                    )
                return fail_return(
                    umsg,
                    current_step="No experts after agent search",
                    store_full_response_error=umsg[:MAX_ERROR_MESSAGE_LENGTH],
                    extra={
                        "target_expert_count": target_expert_count,
                        "agent_error_count": len(agent_errors),
                    },
                )

            try:
                to_persist = _maybe_obfuscate_expert_emails_for_non_production(
                    experts_rows
                )
                replace_count = ExpertPersist.replace_search_experts_for_search(
                    expert_search_id, to_persist
                )
            except Exception as e:
                logger.exception("Expert persist failed search_id=%s", search_id)
                return fail_return(
                    f"Saving experts failed: {e}"[:2000],
                    current_step="Persist failed",
                    exc=e,
                )
            data_persisted = True

            experts = load_experts_for_expert_search(expert_search_id)
            publish_progress("Enriching expert profile links...", 72)
            try:
                SourceEnrichmentService().enrich_experts(experts)
            except Exception:
                logger.exception("Source enrichment failed search_id=%s", search_id)
            publish_progress("Generating PDF report...", 80)
            rows = [expert_to_report_row(e) for e in experts]
            pdf_bytes = generate_pdf_report(rows, query, config)
            publish_progress("Generating CSV file...", 88)
            csv_bytes = generate_csv_file(rows)
            publish_progress("Uploading results to storage...", 94)
            pdf_url = upload_report_to_storage(
                search_id, pdf_bytes, "pdf", "application/pdf"
            )
            csv_url = upload_report_to_storage(search_id, csv_bytes, "csv", "text/csv")
            result: dict[str, Any] = {
                "search_id": search_id,
                "status": ExpertSearch.Status.COMPLETED,
                "query": query,
                "config": config,
                "experts": [],
                "report_urls": {"pdf": pdf_url, "csv": csv_url},
                "expert_count": len(experts),
                "llm_model": llm_model,
            }
            publish_progress(
                "Expert search complete!", 100, status=ExpertSearch.Status.COMPLETED
            )
            logger.info(
                "expert finder search_id=%s completed experts=%s persist=%s",
                search_id,
                len(experts),
                replace_count,
            )
            return result
        except BudgetExceededError:
            raise
        except Exception as e:  # noqa: BLE001
            error_message = f"Expert search processing failed: {e}"
            logger.exception(error_message)
            if not data_persisted:
                clear_expert_search_links(expert_search_id)
            publish_progress(str(e), 0, status=ExpertSearch.Status.FAILED)
            raise


def run_expert_finder_search(
    search_id: str,
    query: str,
    config: dict[str, Any],
    *,
    is_pdf: bool = False,
    additional_context: str | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    return ExpertFinderService().process_expert_search(
        search_id,
        query,
        config,
        is_pdf=is_pdf,
        additional_context=additional_context,
        progress_callback=progress_callback,
    )
