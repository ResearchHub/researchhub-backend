import logging
import re
from typing import Any, Callable

import fitz

from paper.tasks.tasks import create_download_url
from paper.utils import download_pdf_from_url
from research_ai.constants import MAX_PDF_SIZE_BYTES, ExpertiseLevel, Gender, Region
from research_ai.models import Expert, ExpertSearch
from research_ai.prompts.expert_finder_prompts import (
    build_system_prompt,
    build_user_prompt,
)
from research_ai.services.expert_display import (
    build_expert_display_name,
    expert_model_display_name,
    normalize_expert_email,
)
from research_ai.services.expert_llm_table import (
    ExpertTableSchemaError,
    clean_expert_table_url,
    extract_citations_from_notes,
    parse_expert_markdown_table_strict,
)
from research_ai.services.expert_persist import (
    maybe_obfuscate_expert_dict_emails_for_non_production,
    replace_search_experts_for_search,
)
from research_ai.services.openai_expert_finder_service import OpenAIExpertFinderService
from research_ai.services.progress_service import ProgressService, TaskType
from research_ai.services.report_generator_service import (
    generate_csv_file,
    generate_pdf_report,
    upload_report_to_storage,
)
from researchhub_document.related_models.constants.document_type import PAPER

logger = logging.getLogger(__name__)


def _parsed_row_display_name(e: dict[str, Any]) -> str:
    """Single display string from a parsed expert row dict (structured fields only)."""
    return build_expert_display_name(
        honorific=e.get("honorific") or "",
        first_name=e.get("first_name") or "",
        middle_name=e.get("middle_name") or "",
        last_name=e.get("last_name") or "",
        name_suffix=e.get("name_suffix") or "",
    )


PDF_TOO_LARGE_MESSAGE = "PDF is too large. Maximum size is 10 MB. Please use another input type (e.g. abstract)."
MAX_ERROR_MESSAGE_LENGTH = 10000

# Cap on how many times we call the model to "top up" unique experts.
# One API call can return many rows, but duplicates, invalid emails, exclusions, and deceased filtering often leave the
# pool short of the user's target, so we re-prompt with updated exclusions until we reach the target.
EXPERT_FILL_MAX_ROUNDS = 10
EXPERT_FILL_TOLERANCE_SHORT = 4
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


def _get_paper_pdf_bytes(paper) -> bytes | None:
    """
    Get PDF content for a paper. Prefer paper.file (S3); fall back to pdf_url .
    """

    # 1) Prefer paper.file (S3)
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

    # 2) Fall back to pdf_url
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


class ExpertFinderService:
    def __init__(self):
        self.openai_expert = OpenAIExpertFinderService()
        self.progress_service = ProgressService()

    def process_expert_search(
        self,
        search_id: str,
        query: str,
        config: dict[str, Any],
        *,
        excluded_expert_ids: list[int] | None = None,
        is_pdf: bool = False,
        additional_context: str | None = None,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Run expert finder: OpenAI finds experts (web search), parse table, generate reports.

        All operations are synchronous (for use from Celery). Progress is published
        to Redis and optionally to progress_callback(search_id, percent, message).

        is_pdf: Set True when query text was extracted from a PDF (affects prompt wording).
        additional_context: Optional user notes appended to the user prompt for the model.
        """

        def publish_progress_update(
            message: str,
            percent: int,
            status: str = ExpertSearch.Status.PROCESSING,
        ):
            status_val = status.value if hasattr(status, "value") else status
            self.progress_service.publish_progress_sync(
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

        try:
            logger.info("Starting Expert Finder for search_id=%s", search_id)
            expert_count = config.get("expert_count", 10)
            expertise_level_raw = config.get(
                "expertise_level", [ExpertiseLevel.ALL_LEVELS]
            )
            if isinstance(expertise_level_raw, str):
                expertise_level = (
                    [expertise_level_raw]
                    if expertise_level_raw
                    else [ExpertiseLevel.ALL_LEVELS]
                )
            elif expertise_level_raw:
                # Flatten to list of strings (avoid nested lists from JSON)
                expertise_level = []
                for x in expertise_level_raw:
                    if isinstance(x, str):
                        expertise_level.append(x)
                    elif isinstance(x, list):
                        expertise_level.extend(y for y in x if isinstance(y, str))
            else:
                expertise_level = [ExpertiseLevel.ALL_LEVELS]
            region_filter = config.get("region", Region.ALL_REGIONS)
            state_filter = config.get("state", "All States")
            gender_filter = config.get("gender", Gender.ALL_GENDERS)
            excluded_ids = [
                int(x) for x in (excluded_expert_ids or []) if x is not None
            ]
            excluded_emails_from_user: set[str] = set()
            user_excluded_lines: list[str] = []
            if excluded_ids:
                for ex in Expert.objects.filter(id__in=excluded_ids):
                    excluded_emails_from_user.add(normalize_expert_email(ex.email))
                    user_excluded_lines.append(
                        f"id={ex.id}; email={ex.email}; name={expert_model_display_name(ex)}"
                    )
            target_expert_count = max(0, int(expert_count))

            accumulated: list[dict[str, Any]] = []
            seen_email: set[str] = set()
            llm_response = ""
            all_filtered_out = False
            had_user_exclusion = bool(excluded_ids)

            # Each round: one model call asking for up to `remaining` new experts,
            # then parse/filter/dedupe and merge into `accumulated`. We iterate a
            # fixed maximum number of rounds (not "one round per expert") because a
            # single response can return many rows; rounds exist to recover when the
            # first batch is thin after validation. Stops early when we hit the target,
            # when a round adds no new unique experts, or when the "near target"
            # tolerance applies (large targets only).
            for round_num in range(1, EXPERT_FILL_MAX_ROUNDS + 1):
                if len(accumulated) >= target_expert_count:
                    break
                remaining = target_expert_count - len(accumulated)
                # Near-target early exit (large jobs only): e.g. target 100 experts,
                # tolerance 4 → stop once we have ≥96 unique experts. We require
                # target_expert_count > tolerance so small jobs (e.g. need 3, have 2)
                # are not misclassified as "close enough" when remaining ≤ tolerance.
                if (
                    round_num > 1
                    and target_expert_count > EXPERT_FILL_TOLERANCE_SHORT
                    and len(accumulated)
                    >= target_expert_count - EXPERT_FILL_TOLERANCE_SHORT
                ):
                    logger.info(
                        "Expert Finder search_id=%s stopping fill: unique=%s >= "
                        "target - tolerance (%s - %s) after %s rounds",
                        search_id,
                        len(accumulated),
                        target_expert_count,
                        EXPERT_FILL_TOLERANCE_SHORT,
                        round_num - 1,
                    )
                    break

                effective_excluded_lines = self._effective_excluded_lines_for_fill(
                    user_excluded_lines, accumulated
                )
                round_request = max(1, remaining)

                publish_progress_update(
                    "Preparing expert search prompt...", 18 + round_num * 2
                )
                # System role: output format, filters, exclusions. User role: the
                # document/query text and task framing (see expert_finder_prompts).
                finder_system_instructions = build_system_prompt(
                    expert_count=round_request,
                    expertise_level=expertise_level,
                    region_filter=region_filter,
                    state_filter=state_filter,
                    gender_filter=gender_filter,
                    excluded_expert_lines=effective_excluded_lines,
                )
                finder_user_task = build_user_prompt(
                    query=query,
                    expert_count=round_request,
                    expertise_level=expertise_level,
                    region_filter=region_filter,
                    gender_filter=gender_filter,
                    is_pdf=is_pdf,
                    additional_context=additional_context,
                )

                publish_progress_update(
                    f"Finding experts (round {round_num}/{EXPERT_FILL_MAX_ROUNDS}, "
                    f"{len(accumulated)}/{target_expert_count})...",
                    38 + round_num * 4,
                )
                llm_response = self.openai_expert.invoke(
                    system_prompt=finder_system_instructions,
                    user_prompt=finder_user_task,
                )
                logger.info(
                    "OpenAI expert finder search_id=%s round=%s response_len=%s",
                    search_id,
                    round_num,
                    len(llm_response),
                )

                publish_progress_update(
                    "Parsing expert recommendations...", 58 + round_num * 2
                )
                try:
                    batch = parse_expert_markdown_table_strict(llm_response)
                except ExpertTableSchemaError as e:
                    err_text = str(e)
                    msg = (
                        "The model response did not match the required expert table format. "
                        f"{err_text}"
                    )
                    publish_progress_update(msg, 0, status=ExpertSearch.Status.FAILED)
                    if progress_callback:
                        progress_callback(search_id, 0, msg)
                    return {
                        "search_id": search_id,
                        "status": ExpertSearch.Status.FAILED,
                        "query": query,
                        "config": config,
                        "report_urls": {},
                        "expert_count": 0,
                        "llm_model": self.openai_expert.model_id,
                        "error_message": err_text[:MAX_ERROR_MESSAGE_LENGTH],
                        "current_step": "Model output did not match required table format",
                    }
                parsed_count = len(batch)

                before_name_filter = len(batch)
                accumulated_names = [
                    nm
                    for x in accumulated
                    if (nm := _parsed_row_display_name(x)).strip()
                ]
                combined_name_exclusions = list(accumulated_names)
                batch = [
                    e
                    for e in batch
                    if normalize_expert_email(e.get("email"))
                    not in excluded_emails_from_user
                ]
                batch = [
                    e
                    for e in batch
                    if not self._expert_name_matches_excluded(
                        _parsed_row_display_name(e), combined_name_exclusions
                    )
                ]
                after_exclude = len(batch)
                if (
                    round_num == 1
                    and had_user_exclusion
                    and before_name_filter > 0
                    and after_exclude == 0
                ):
                    all_filtered_out = True

                batch = [e for e in batch if not self._expert_row_suggests_deceased(e)]
                after_deceased = len(batch)

                batch = self._dedupe_experts_by_normalized_email(batch)
                after_dedupe = len(batch)

                before_merge_len = len(accumulated)
                for e in batch:
                    em = (e.get("email") or "").strip().lower()
                    if not em or em in seen_email:
                        continue
                    seen_email.add(em)
                    accumulated.append(dict(e))
                new_added = len(accumulated) - before_merge_len

                logger.info(
                    "Expert Finder search_id=%s round=%s: parsed=%s after_name_filter=%s "
                    "after_deceased_filter=%s after_batch_dedupe=%s new_unique_merged=%s "
                    "total_unique=%s target=%s",
                    search_id,
                    round_num,
                    parsed_count,
                    after_exclude,
                    after_deceased,
                    after_dedupe,
                    new_added,
                    len(accumulated),
                    target_expert_count,
                )

                if new_added == 0:
                    break

            experts = accumulated[:target_expert_count]
            logger.info(
                "Expert Finder search_id=%s fill complete: unique=%s after_cap=%s target=%s",
                search_id,
                len(accumulated),
                len(experts),
                target_expert_count,
            )

            if len(experts) == 0:
                if all_filtered_out:
                    msg = (
                        "All recommended experts were in the exclusion list. "
                        "The model did not suggest new names; try broadening your criteria."
                    )
                    current_step = "All experts excluded; no new recommendations"
                    error_message = msg[:MAX_ERROR_MESSAGE_LENGTH]
                else:
                    msg = (
                        "No expert recommendations table was returned. "
                        "The model response could not be parsed as a markdown table."
                    )
                    llm_error = (llm_response or "").strip()
                    if llm_error:
                        display_error = llm_error[:MAX_ERROR_MESSAGE_LENGTH] + (
                            "..." if len(llm_error) > MAX_ERROR_MESSAGE_LENGTH else ""
                        )
                        msg = msg + " Response from model:\n\n" + display_error
                    current_step = "No expert recommendations table returned by model"
                    error_message = (llm_response or "")[:MAX_ERROR_MESSAGE_LENGTH]
                publish_progress_update(msg, 0, status=ExpertSearch.Status.FAILED)
                if progress_callback:
                    progress_callback(search_id, 0, msg)
                return {
                    "search_id": search_id,
                    "status": ExpertSearch.Status.FAILED,
                    "query": query,
                    "config": config,
                    "report_urls": {},
                    "expert_count": 0,
                    "llm_model": self.openai_expert.model_id,
                    "error_message": error_message,
                    "current_step": current_step,
                }
            to_store = maybe_obfuscate_expert_dict_emails_for_non_production(
                [dict(e) for e in experts]
            )
            stored_experts = replace_search_experts_for_search(int(search_id), to_store)
            publish_progress_update("Generating PDF report...", 80)
            pdf_bytes = generate_pdf_report(stored_experts, query, config)
            publish_progress_update("Generating CSV file...", 88)
            csv_bytes = generate_csv_file(stored_experts)

            publish_progress_update("Uploading results to storage...", 94)
            pdf_url = upload_report_to_storage(
                search_id, pdf_bytes, "pdf", "application/pdf"
            )
            csv_url = upload_report_to_storage(search_id, csv_bytes, "csv", "text/csv")

            result = {
                "search_id": search_id,
                "status": ExpertSearch.Status.COMPLETED,
                "query": query,
                "config": config,
                "report_urls": {"pdf": pdf_url, "csv": csv_url},
                "expert_count": len(stored_experts),
                "llm_model": self.openai_expert.model_id,
            }
            publish_progress_update(
                "Expert search complete!", 100, status=ExpertSearch.Status.COMPLETED
            )
            if progress_callback:
                progress_callback(search_id, 100, "Expert search complete!")
            return result

        except Exception as e:
            error_message = f"Expert search processing failed: {str(e)}"
            logger.exception(error_message)
            publish_progress_update(error_message, 0, status=ExpertSearch.Status.FAILED)
            if progress_callback:
                progress_callback(search_id, 0, error_message)
            raise

    def _extract_citations(self, text: str) -> tuple[str, list[dict[str, str]]]:
        """Extract markdown links [text](url) from notes; return (cleaned_text, citations)."""
        return extract_citations_from_notes(text)

    def _clean_url(self, url: str) -> str:
        """Remove UTM and tracking query params."""
        return clean_expert_table_url(url)

    @staticmethod
    def _expert_row_suggests_deceased(expert: dict[str, Any]) -> bool:
        """
        True if name/title/affiliation/expertise/notes contain obvious deceased indicators.

        Conservative: only flags clear phrases (e.g. deceased, late Prof., d. 2020).
        """
        parts = [
            _parsed_row_display_name(expert),
            expert.get("honorific") or "",
            expert.get("first_name") or "",
            expert.get("middle_name") or "",
            expert.get("last_name") or "",
            expert.get("name_suffix") or "",
            expert.get("academic_title") or "",
            expert.get("affiliation") or "",
            expert.get("expertise") or "",
            expert.get("notes") or "",
        ]
        blob = " ".join(p.strip() for p in parts if p and str(p).strip())
        if not blob:
            return False
        return _DECEASED_ROW_REGEX.search(blob) is not None

    @staticmethod
    def _normalize_name_for_exclusion(name: str) -> str:
        """Normalize expert name for exclusion matching: lowercase, strip, collapse spaces."""
        if not name or not isinstance(name, str):
            return ""
        s = name.strip().lower()
        for prefix in ("dr.", "prof.", "professor ", "mr.", "mrs.", "ms."):
            if s.startswith(prefix):
                s = s[len(prefix) :].strip()
        for suffix in (", phd", ", md", ", jr.", ", sr.", " phd", " md"):
            if s.endswith(suffix):
                s = s[: -len(suffix)].strip()
        return " ".join(s.split())

    def _expert_name_matches_excluded(
        self, expert_name: str, excluded_names: list[str]
    ) -> bool:
        """Return True if expert_name should be excluded (matches any excluded name).

        Matching is by whole tokens (words), not substrings, so e.g. excluding "Li"
        does not match "Oliver" (no token "li" in expert name).
        """
        if not excluded_names or not expert_name:
            return False
        expert_norm = self._normalize_name_for_exclusion(expert_name)
        if not expert_norm:
            return False
        expert_tokens = set(expert_norm.split())
        for excluded in excluded_names:
            excluded_norm = self._normalize_name_for_exclusion(excluded)
            if not excluded_norm:
                continue
            excluded_tokens = excluded_norm.split()
            if not excluded_tokens:
                continue
            if expert_norm == excluded_norm:
                return True
            if all(token in expert_tokens for token in excluded_tokens):
                return True
        return False

    @staticmethod
    def _dedupe_experts_by_normalized_email(
        experts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Keep first row per email; normalize email with strip().lower() for identity.
        Stored expert dicts use the normalized email string.
        """
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for e in experts:
            raw = (e.get("email") or "").strip()
            if not raw:
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
    def _effective_excluded_lines_for_fill(
        user_excluded_lines: list[str],
        accumulated: list[dict[str, Any]],
    ) -> list[str]:
        """
        Lines for the model (id/email/name): user exclusions plus experts already collected.
        Capped to avoid oversized prompts.
        """
        acc_lines = []
        for e in accumulated:
            em = (e.get("email") or "").strip()
            nm = _parsed_row_display_name(e).strip()
            if em or nm:
                acc_lines.append(f"email={em}; name={nm}")
        combined = list(user_excluded_lines) + acc_lines
        if len(combined) <= EXPERT_FILL_EXCLUDED_NAMES_CAP:
            return combined
        n_user = len(user_excluded_lines)
        if n_user >= EXPERT_FILL_EXCLUDED_NAMES_CAP:
            logger.warning(
                "Expert fill: user exclusion list length %s exceeds cap %s; truncating",
                n_user,
                EXPERT_FILL_EXCLUDED_NAMES_CAP,
            )
            return list(user_excluded_lines)[:EXPERT_FILL_EXCLUDED_NAMES_CAP]
        tail = EXPERT_FILL_EXCLUDED_NAMES_CAP - n_user
        logger.warning(
            "Expert fill: exclusion list capped to %s (user=%s accumulated_lines=%s)",
            EXPERT_FILL_EXCLUDED_NAMES_CAP,
            n_user,
            len(acc_lines),
        )
        return list(user_excluded_lines) + acc_lines[-tail:]

    def _parse_markdown_table(self, markdown_text: str) -> list[dict[str, Any]]:
        """Parse markdown table using the strict LLM schema (for tests and tooling)."""
        return parse_expert_markdown_table_strict(markdown_text)
