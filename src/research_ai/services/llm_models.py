"""The model each LLM-backed feature calls, in one place.

A role is one feature's model: the provider that serves it and the model id in
that provider's own format. Moving a feature to a newer model is a change to
its role here, plus a reviewed row in ``agent.model_capabilities`` (and in
``agent.model_pricing`` for models the agent bills). What a model accepts,
such as ``temperature``, is read from those capabilities, never from the id.

A role with a ``setting`` takes a non-empty Django setting of that name as an
override, for environments that pin a different model.

The agent picker's catalog and tier defaults are product policy and stay in
``agent.model_catalog`` and ``usage_budget.config``.
"""

from dataclasses import dataclass

from django.conf import settings

BEDROCK = "bedrock"
CLAUDE_PLATFORM = "claude_platform"
OPENAI = "openai"
OPENROUTER = "openrouter"


@dataclass(frozen=True)
class ModelRole:
    """One feature's model: provider, default model id, optional override."""

    provider: str
    default: str
    setting: str | None = None

    @property
    def model_id(self) -> str:
        override = getattr(settings, self.setting, "") if self.setting else ""
        return override or self.default


# What each agent adapter runs when a model ref names no model.
CLAUDE_PLATFORM_AGENT = ModelRole(CLAUDE_PLATFORM, "claude-opus-5-5")
# Bedrock needs the ``us.`` cross-region profile; the bare
# ``anthropic.claude-opus-5-5`` serves only in-Region from eu-west-2.
BEDROCK_AGENT = ModelRole(BEDROCK, "us.anthropic.claude-opus-5-5")
OPENROUTER_AGENT = ModelRole(OPENROUTER, "anthropic/claude-opus-5.5")

# Single-purpose features.
PRIMARY_IMAGE = ModelRole(BEDROCK, "us.anthropic.claude-haiku-5-5")
# Expert profile matching and outreach emails.
RESEARCH_AI_BEDROCK = ModelRole(
    BEDROCK, "us.anthropic.claude-haiku-5-5", "RESEARCH_AI_BEDROCK_MODEL_ID"
)
EXPERT_FINDER = ModelRole(OPENAI, "gpt-6-luna")
PEER_REVIEW = ModelRole(
    BEDROCK, "us.anthropic.claude-haiku-5-5", "AI_PEER_REVIEW_BEDROCK_MODEL_ID"
)
PEER_REVIEW_WEB_CONTEXT = ModelRole(
    OPENAI, "gpt-6-luna", "AI_PEER_REVIEW_OPENAI_WEB_CONTEXT_MODEL"
)
# Stays on K3: posts run with reasoning off under a short timeout, and K3.1 Pro
# always reasons.
SOCIAL_SHARE = ModelRole(OPENROUTER, "moonshotai/kimi-k3")

ROLES = (
    CLAUDE_PLATFORM_AGENT,
    BEDROCK_AGENT,
    OPENROUTER_AGENT,
    PRIMARY_IMAGE,
    RESEARCH_AI_BEDROCK,
    EXPERT_FINDER,
    PEER_REVIEW,
    PEER_REVIEW_WEB_CONTEXT,
    SOCIAL_SHARE,
)

# Where a research_ai conversation moves once its own model refuses a turn. It
# needs reviewed pricing.
REFUSAL_FALLBACK = "openrouter:moonshotai/kimi-k3.1-pro"


def refusal_fallback_ref() -> str | None:
    """The refusal fallback ref, or ``None`` when the setting turns moves off.

    An unset ``RESEARCH_AI_REFUSAL_FALLBACK_MODEL`` means the default; an empty
    one stops new moves, not ones already made.
    """
    value = getattr(settings, "RESEARCH_AI_REFUSAL_FALLBACK_MODEL", None)
    if value is None:
        return REFUSAL_FALLBACK
    return value or None
