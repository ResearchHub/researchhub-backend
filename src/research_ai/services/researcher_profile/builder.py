"""Public entry points for the researcher-profile agent.

``build_expert_profile`` runs the agent (no write); ``build_and_store_expert_profile``
persists the result on ``Expert.profile`` so it is reused instead of rebuilt.
"""

import logging

from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.researcher_profile.agent import run_profile_agent
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)


def build_expert_profile(
    expert,
    *,
    llm: BedrockLLMService | None = None,
    oa_client: OpenAlex | None = None,
) -> dict:
    """Build the source-attributed researcher profile for an ``Expert`` (no write)."""
    return run_profile_agent(expert, llm=llm, oa_client=oa_client)


def build_and_store_expert_profile(expert, **kwargs) -> dict:
    """Build the profile and persist it on ``Expert.profile`` (built once, reused)."""
    profile = build_expert_profile(expert, **kwargs)
    expert.profile = profile
    expert.save(update_fields=["profile", "updated_date"])
    return profile
