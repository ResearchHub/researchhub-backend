import logging
from typing import Any

from research_ai.constants import EXPERT_FINDER_DEFAULT_STATE
from research_ai.prompts.expert_finder_prompts import (
    build_system_prompt,
    build_user_prompt,
)
from research_ai.services.expert_finder.email_validation import EmailValidationService
from research_ai.services.expert_finder.json_parsing import ExpertFinderJson
from research_ai.services.expert_finder.openai_finder import OpenAIExpertFinderService

logger = logging.getLogger(__name__)


def run_gpt_expert_finder(
    *,
    query: str,
    expert_count: int,
    expertise_level: list[str] | str,
    region_filter: str,
    state_filter: str = EXPERT_FINDER_DEFAULT_STATE,
    excluded_expert_names: list[str] | None = None,
    additional_context: str | None = None,
    is_pdf: bool = False,
    openai_service: OpenAIExpertFinderService | None = None,
    email_validation: EmailValidationService | None = None,
) -> dict[str, Any]:
    """Run GPT expert discovery and return SES-gated expert rows.

    Returns:
        ``{"experts", "errors", "llm_model"}``

    Raises:
        RuntimeError: OpenAI invoke / missing key failures from the service.
        ValueError: JSON parse or structure validation failures.
    """
    errors: list[str] = []
    openai = openai_service or OpenAIExpertFinderService()
    email_service = email_validation or EmailValidationService()
    target = max(1, int(expert_count))

    system_prompt = build_system_prompt(
        expert_count=target,
        expertise_level=expertise_level,
        region_filter=region_filter,
        state_filter=state_filter,
        excluded_expert_names=excluded_expert_names or [],
    )
    user_prompt = build_user_prompt(
        query=query,
        expert_count=target,
        expertise_level=expertise_level,
        region_filter=region_filter,
        is_pdf=is_pdf,
        additional_context=additional_context,
    )

    logger.info(
        "GPT expert-finder starting model=%s target=%s",
        openai.model_id,
        target,
    )
    llm_response = openai.invoke(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    obj = ExpertFinderJson.parse_text(llm_response)
    batch = ExpertFinderJson.validate_output(obj)
    kept, drops = email_service.gate_submitted_experts(batch)
    errors.extend(drops)
    if drops:
        logger.info(
            "GPT expert search SES gate dropped %s of %s experts",
            len(drops),
            len(batch),
        )

    return {
        "experts": kept[:target],
        "errors": errors,
        "llm_model": f"openai:{openai.model_id}",
    }
