import logging
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import fitz
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from paper.tasks.tasks import create_download_url
from paper.utils import download_pdf_from_url
from research_ai.constants import (
    EXPERT_FINDER_DEFAULT_STATE,
    MAX_PDF_SIZE_BYTES,
    ExpertiseLevel,
    Region,
)
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.prompts.expert_finder_prompts import (
    build_system_prompt,
    build_user_prompt,
)
from research_ai.services.expert_display import ExpertDisplay
from research_ai.services.expert_finder_json import ExpertFinderJson
from research_ai.services.expert_persist import ExpertPersist
from research_ai.services.openai_expert_finder_service import OpenAIExpertFinderService
from research_ai.services.progress_service import ProgressService, TaskType
from research_ai.services.report_generator_service import (
    expert_to_report_row,
    generate_csv_file,
    generate_pdf_report,
    upload_report_to_storage,
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

EXPERT_FILL_MAX_ROUNDS = 6
EXPERT_FILL_TOLERANCE_SHORT = 10
EXPERT_FILL_EXCLUDED_NAMES_CAP = 250
EXPERT_FILL_BATCH_MAX = 50

PROMPT_EXPERT_HEADROOM_PCT = 10

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


def _get_paper_pdf_bytes(paper) -> bytes | None:
    """
    Get PDF content for a paper. Prefer paper.file (S3); fall back to pdf_url .
    """

    if getattr(paper, "file", None) and getattr(paper.file, "url", None):
        try:
            pdf_file = download_pdf_from_url(paper.file.url)
            return pdf_file.read()
        except Exception as e:
            logger.warning(
                "Failed to get PDF from paper.file for paper %s: %s. Trying pdf_url.",
                getattr(paper, "id", "?"),
                e,
            )

    pdf_url = getattr(paper, "pdf_url", None) or getattr(paper, "url", None)
    if not pdf_url:
        return None
    try:
        url = create_download_url(pdf_url, getattr(paper, "external_source", "") or "")
        pdf_file = download_pdf_from_url(url)
        return pdf_file.read()
    except Exception as e:
        logger.warning(
            "Failed to download PDF from pdf_url for paper %s: %s",
            getattr(paper, "id", "?"),
            e,
            exc_info=True,
        )
        return None


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Extract text from PDF bytes using PyMuPDF
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        text = "\n".join(parts)
        return text[:200000] if len(text) > 200000 else text
    except Exception as e:
        logger.warning("Failed to extract text from PDF: %s", e)
        raise ValueError(f"PDF text extraction failed: {e}") from e


def _prompt_expert_count_for_round(remaining: int) -> int:
    need = max(1, remaining)
    with_headroom = (need * (100 + PROMPT_EXPERT_HEADROOM_PCT) + 99) // 100
    return min(with_headroom, EXPERT_FILL_BATCH_MAX)


def clear_expert_search_links(expert_search_id: int) -> None:
    """Remove non-manual SearchExpert links (e.g. after a failed LLM run)."""
    SearchExpert.objects.filter(
        expert_search_id=expert_search_id,
        expert__is_manually_added=False,
    ).delete()


def load_experts_for_expert_search(expert_search_id: int) -> list[Expert]:
    qs = (
        SearchExpert.objects.filter(expert_search_id=expert_search_id)
        .select_related("expert")
        .order_by("position")
    )
    return [se.expert for se in qs]


def _names_and_emails_from_excluded_searches(
    excluded_search_ids: list[int] | None,
) -> tuple[list[str], set[str]]:
    if not excluded_search_ids:
        return [], set()
    out_names: list[str] = []
    out_emails: set[str] = set()
    qs = SearchExpert.objects.filter(
        expert_search_id__in=excluded_search_ids
    ).select_related("expert")
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
        self.openai_expert = OpenAIExpertFinderService()
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
    def _accumulated_display_names(accumulated: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for e in accumulated:
            n = (e.get("name") or "").strip()
            if n:
                names.append(n)
                continue
            lab = ExpertDisplay.build_name(
                honorific=e.get("honorific") or "",
                first_name=e.get("first_name") or "",
                middle_name=e.get("middle_name") or "",
                last_name=e.get("last_name") or "",
                name_suffix=e.get("name_suffix") or "",
            ).strip()
            if lab:
                names.append(lab)
        return names

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
    def _effective_excluded_for_fill(
        user_excluded: list[str],
        accumulated: list[dict[str, Any]],
    ) -> list[str]:
        acc_names = ExpertFinderService._accumulated_display_names(accumulated)
        combined = list(user_excluded) + acc_names
        if len(combined) <= EXPERT_FILL_EXCLUDED_NAMES_CAP:
            return combined
        n_user = len(user_excluded)
        if n_user >= EXPERT_FILL_EXCLUDED_NAMES_CAP:
            logger.warning(
                "Expert fill: user exclusion list length %s exceeds cap %s; truncating",
                n_user,
                EXPERT_FILL_EXCLUDED_NAMES_CAP,
            )
            return list(user_excluded)[:EXPERT_FILL_EXCLUDED_NAMES_CAP]
        tail = EXPERT_FILL_EXCLUDED_NAMES_CAP - n_user
        logger.warning(
            "Expert fill: exclusion list capped to %s (user=%s accumulated_names=%s)",
            EXPERT_FILL_EXCLUDED_NAMES_CAP,
            n_user,
            len(acc_names),
        )
        return list(user_excluded) + acc_names[-tail:]

    def process_expert_search(
        self,
        search_id: str,
        query: str,
        config: dict[str, Any],
        *,
        excluded_search_ids: list[int] | None = None,
        is_pdf: bool = False,
        additional_context: str | None = None,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> dict[str, Any]:
        expert_search_id = int(search_id)
        progress_service = self.progress_service
        openai = self.openai_expert

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
        ) -> dict[str, Any]:
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
                "llm_model": openai.model_id,
                "error_message": err,
                "current_step": current_step[:512],
            }

        data_persisted = False
        try:
            search_id_names, search_id_emails = (
                _names_and_emails_from_excluded_searches(excluded_search_ids)
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
            llm_response = ""
            accumulated: list[dict[str, Any]] = []
            all_filtered_by_exclusion = False

            for round_num in range(1, EXPERT_FILL_MAX_ROUNDS + 1):
                if len(accumulated) >= target_expert_count:
                    break

                if (
                    round_num > 1
                    and target_expert_count > EXPERT_FILL_TOLERANCE_SHORT
                    and len(accumulated)
                    >= target_expert_count - EXPERT_FILL_TOLERANCE_SHORT
                ):
                    break

                remaining = target_expert_count - len(accumulated)
                prompt_expert_count = _prompt_expert_count_for_round(remaining)
                names_from_prior_searches = [n for n in search_id_names if n]
                effective_excluded = self._effective_excluded_for_fill(
                    names_from_prior_searches,
                    accumulated,
                )

                publish_progress(
                    "Preparing expert search prompt...", 18 + round_num * 2
                )
                finder_system = build_system_prompt(
                    expert_count=prompt_expert_count,
                    expertise_level=expertise_level,
                    region_filter=region_filter,
                    state_filter=state_filter,
                    excluded_expert_names=effective_excluded,
                )
                finder_user = build_user_prompt(
                    query=query,
                    expert_count=prompt_expert_count,
                    expertise_level=expertise_level,
                    region_filter=region_filter,
                    is_pdf=is_pdf,
                    additional_context=additional_context,
                )
                publish_progress(
                    f"Finding experts (round {round_num}/{EXPERT_FILL_MAX_ROUNDS}, "
                    f"{len(accumulated)}/{target_expert_count})...",
                    38 + round_num * 4,
                )
                llm_response = openai.invoke(
                    system_prompt=finder_system,
                    user_prompt=finder_user,
                )
                publish_progress(
                    "Parsing expert recommendations (JSON)...",
                    58 + round_num * 2,
                )
                try:
                    obj = ExpertFinderJson.parse_text(llm_response)
                except ValueError as e:
                    return fail_return(
                        "No valid JSON object was returned. "
                        "The model output could not be parsed.",
                        current_step="JSON parse failed",
                        store_full_response_error=(
                            (llm_response or "").strip()[:MAX_ERROR_MESSAGE_LENGTH]
                        )
                        or str(e)[:MAX_ERROR_MESSAGE_LENGTH],
                    )
                try:
                    batch = ExpertFinderJson.validate_output(obj)
                except ValueError as e:
                    return fail_return(
                        f"Invalid expert JSON structure: {e}"[:2000],
                        current_step="Expert output validation failed",
                    )

                n_before = len(batch)
                kept: list[dict[str, Any]] = []
                for row in batch:
                    em = (row.get("email") or "").strip().lower()
                    if not em:
                        continue
                    if search_id_emails and em in search_id_emails:
                        continue
                    kept.append(row)
                if round_num == 1 and search_id_emails and n_before > 0 and not kept:
                    all_filtered_by_exclusion = True

                batch = [r for r in kept if not self._expert_row_suggests_deceased(r)]

                batch = self._dedupe_experts_by_normalized_email(batch)

                acc_before = len(accumulated)
                accumulated = self._dedupe_experts_by_normalized_email(
                    accumulated + batch
                )
                if len(accumulated) == acc_before:
                    break

                if len(accumulated) >= target_expert_count:
                    break

            experts_rows = accumulated[:target_expert_count]
            if len(experts_rows) == 0:
                if all_filtered_by_exclusion:
                    umsg = (
                        "Every recommendation matched an email from a prior search "
                        "you excluded. Try broadening criteria or adjust excluded searches."
                    )
                    return fail_return(umsg, current_step="All experts excluded")

                umsg = (
                    "No expert recommendations were returned. The model did not return "
                    "usable JSON with at least one valid expert."
                )
                llm_err = (llm_response or "").strip()
                if llm_err:
                    umsg = (
                        umsg
                        + " Response from model:\n\n"
                        + llm_err[:MAX_ERROR_MESSAGE_LENGTH]
                    )
                return fail_return(
                    umsg,
                    current_step="No experts after parsing",
                    store_full_response_error=(
                        llm_err[:MAX_ERROR_MESSAGE_LENGTH] or umsg
                    ),
                )

            try:
                to_persist = _maybe_obfuscate_expert_emails_for_non_production(
                    experts_rows
                )
                replace_count = ExpertPersist.replace_search_experts_for_search(
                    expert_search_id, to_persist
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("Expert persist failed search_id=%s: %s", search_id, e)
                return fail_return(
                    f"Saving experts failed: {e}"[:2000],
                    current_step="Persist failed",
                )
            data_persisted = True

            experts = load_experts_for_expert_search(expert_search_id)
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
                "llm_model": openai.model_id,
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
    excluded_search_ids: list[int] | None = None,
    is_pdf: bool = False,
    additional_context: str | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    return ExpertFinderService().process_expert_search(
        search_id,
        query,
        config,
        excluded_search_ids=excluded_search_ids,
        is_pdf=is_pdf,
        additional_context=additional_context,
        progress_callback=progress_callback,
    )
