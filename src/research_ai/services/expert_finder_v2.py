import logging
import math
from collections.abc import Callable
from typing import Any

from research_ai.constants import ExpertiseLevel, Region
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.prompts.expert_finder_prompts import (
    build_system_prompt_v2,
    build_user_prompt,
)
from research_ai.services.expert_display import expert_model_display_name
from research_ai.services.expert_finder_json import (
    parse_expert_finder_json_text,
    validate_expert_output,
)
from research_ai.services.expert_finder_service import (
    _DECEASED_ROW_REGEX,
    EXPERT_FILL_MAX_ROUNDS,
    EXPERT_FILL_TOLERANCE_SHORT,
    MAX_ERROR_MESSAGE_LENGTH,
    ExpertFinderService,
)
from research_ai.services.expert_persist import replace_search_experts_for_search
from research_ai.services.progress_service import TaskType
from research_ai.services.report_generator_service import (
    generate_csv_file_v2,
    generate_pdf_report_v2,
    upload_report_to_storage,
)

logger = logging.getLogger(__name__)

V2_PROMPT_EXPERT_RESERVE_PCT = 0.1


def _prompt_expert_count_for_round(remaining: int) -> int:
    """
    How many experts to ask for in system/user prompts for this fill round.

    We ask for ~10% more (rounded up) to absorb duplicates that are dropped in deduplication.
    """
    base = max(1, remaining)
    return max(base, math.ceil(base * (1.0 + V2_PROMPT_EXPERT_RESERVE_PCT)))


def clear_expert_search_links(expert_search_id: int) -> None:
    """
    v2: delete SearchExpert rows for this search (e.g. parse/validate failure, or
    so a failed run does not leave stale membership rows).
    """
    SearchExpert.objects.filter(expert_search_id=expert_search_id).delete()


def load_experts_for_expert_search(expert_search_id: int) -> list[Expert]:
    """
    Return ``Expert`` rows linked to this search.
    """
    qs = (
        SearchExpert.objects.filter(expert_search_id=expert_search_id)
        .select_related("expert")
        .order_by("position")
    )
    return [se.expert for se in qs]


# TODO: We probably need to get only first name last name with no title.
def _names_and_emails_from_excluded_searches(
    excluded_search_ids: list[int] | None,
) -> tuple[list[str], set[str]]:
    """Load display names and emails from experts in the given past searches."""
    if not excluded_search_ids:
        return [], set()
    out_names: list[str] = []
    out_emails: set[str] = set()
    qs = SearchExpert.objects.filter(
        expert_search_id__in=excluded_search_ids
    ).select_related("expert")
    for se in qs:
        e = se.expert
        label = expert_model_display_name(e)
        if label:
            out_names.append(label)
        em = (e.email or "").strip().lower()
        if em:
            out_emails.add(em)
    return out_names, out_emails


class ExpertFinderServiceV2(ExpertFinderService):

    @staticmethod
    def _expert_row_suggests_deceased_v2(row: dict[str, Any]) -> bool:
        """
        True if name/title/affiliation/expertise/notes contain obvious deceased indicators.

        Conservative: only flags clear phrases (e.g. deceased, late Prof., d. 2020).
        """
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

    def process_expert_search_v2(
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
        """
        Run expert finder: OpenAI finds experts (web search), parse table, generate reports.

        All operations are synchronous (for use from Celery). Progress is published
        to Redis and optionally to progress_callback(search_id, percent, message).

        is_pdf: Set True when query text was extracted from a PDF (affects prompt wording).
        additional_context: Optional user notes appended to the user prompt for the model.
        """
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
            state_filter = config.get("state", "All States")
            llm_response = ""
            accumulated: list[dict[str, Any]] = []
            all_filtered_by_exclusion = False

            # Each round: one model call asking for (remaining + reserve) experts in
            # the prompt—more than the gap we need, so dedupes still let us fill—then
            # parse/filter/dedupe and merge into `accumulated`. We iterate a
            # fixed maximum number of rounds (not "one round per expert") because a
            # single response can return many rows; rounds exist to recover when the
            # first batch is thin after validation. Stops early when we hit the target,
            # when a round adds no new unique experts, or when the "near target"
            # tolerance applies (large targets only).
            for round_num in range(1, EXPERT_FILL_MAX_ROUNDS + 1):
                if len(accumulated) >= target_expert_count:
                    break

                # Near-target early exit (large jobs only): e.g. target 100 experts,
                # tolerance 10 → stop once we have ≥90 unique experts. We require
                # target_expert_count > tolerance so small jobs (e.g. need 3, have 2)
                # are not misclassified as "close enough" when remaining ≤ tolerance.
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
                    "Preparing expert search prompt (v2)...", 18 + round_num * 2
                )
                finder_system = build_system_prompt_v2(
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
                    f"Finding experts (v2, round {round_num}/{EXPERT_FILL_MAX_ROUNDS}, "
                    f"{len(accumulated)}/{target_expert_count})...",
                    38 + round_num * 4,
                )
                llm_response = openai.invoke(
                    system_prompt=finder_system,
                    user_prompt=finder_user,
                )
                publish_progress(
                    "Parsing expert recommendations (v2 JSON)...",
                    58 + round_num * 2,
                )
                try:
                    obj = parse_expert_finder_json_text(llm_response)
                except ValueError as e:
                    return fail_return(
                        "No valid JSON object was returned. The model output could not be parsed.",
                        current_step="JSON parse failed",
                        store_full_response_error=(
                            (llm_response or "").strip()[:MAX_ERROR_MESSAGE_LENGTH]
                        )
                        or str(e)[:MAX_ERROR_MESSAGE_LENGTH],
                    )
                try:
                    batch = validate_expert_output(obj)
                except ValueError as e:
                    return fail_return(
                        f"Invalid expert JSON structure: {e}"[:2000],
                        current_step="v2: output validation failed",
                    )

                # Here we drop rows whose email matches an expert from an excluded search.
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

                batch = [
                    r for r in kept if not self._expert_row_suggests_deceased_v2(r)
                ]

                batch = self._dedupe_experts_by_normalized_email(batch)
                accumulated.extend(batch)

                if len(accumulated) >= target_expert_count:
                    break

            experts_rows = accumulated[:target_expert_count]
            if len(experts_rows) == 0:
                if all_filtered_by_exclusion:
                    umsg = (
                        "Every recommendation matched an email from a prior search you excluded. "
                        "Try broadening criteria or adjust excluded searches."
                    )
                    return fail_return(umsg, current_step="All v2 experts excluded")

                umsg = (
                    "No expert recommendations were returned. "
                    "The model did not return usable JSON with at least one valid expert."
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
                    current_step="v2: no experts after parsing",
                    store_full_response_error=(
                        llm_err[:MAX_ERROR_MESSAGE_LENGTH] or umsg
                    ),
                )

            try:
                replace_count = replace_search_experts_for_search(
                    expert_search_id, experts_rows
                )
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "v2 expert persist failed search_id=%s: %s", search_id, e
                )
                return fail_return(
                    f"Saving experts failed: {e}"[:2000],
                    current_step="v2: persist failed",
                )
            data_persisted = True

            experts = load_experts_for_expert_search(expert_search_id)
            publish_progress("Generating PDF report...", 80)
            pdf_bytes = generate_pdf_report_v2(experts, query, config)
            publish_progress("Generating CSV file...", 88)
            csv_bytes = generate_csv_file_v2(experts)
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
                "experts": [],  # Deprecated: v2 no longer returns inline expert rows.
                "report_urls": {"pdf": pdf_url, "csv": csv_url},
                "expert_count": len(experts),
                "llm_model": openai.model_id,
            }
            publish_progress(
                "Expert search complete!", 100, status=ExpertSearch.Status.COMPLETED
            )
            logger.info(
                "v2 expert finder search_id=%s completed experts=%s persist=%s",
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


def run_v2_expert_search(
    search_id: str,
    query: str,
    config: dict[str, Any],
    *,
    excluded_search_ids: list[int] | None = None,
    is_pdf: bool = False,
    additional_context: str | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    """Convenience entrypoint: one-shot ``ExpertFinderServiceV2`` instance."""
    return ExpertFinderServiceV2().process_expert_search_v2(
        search_id,
        query,
        config,
        excluded_search_ids=excluded_search_ids,
        is_pdf=is_pdf,
        additional_context=additional_context,
        progress_callback=progress_callback,
    )
