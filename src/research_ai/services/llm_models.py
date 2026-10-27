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


# Each model once, in its provider's own id format. Named by family rather
# than version, so moving every feature on a family to a newer model is one
# line here.
CLAUDE_OPUS = "claude-opus-5-5"
# Bedrock needs the ``us.`` cross-region profile; the bare
# ``anthropic.claude-opus-5-5`` serves only in-Region from eu-west-2.
BEDROCK_CLAUDE_OPUS = "us.anthropic.claude-opus-5-5"
BEDROCK_CLAUDE_HAIKU = "us.anthropic.claude-haiku-5-5"
OPENROUTER_CLAUDE_OPUS = "anthropic/claude-opus-5.5"
OPENROUTER_KIMI = "moonshotai/kimi-k3.1-pro"
# Pinned: social-share posts run with reasoning off under a short timeout, and
# K3 is cheaper per input token for that short job.
OPENROUTER_KIMI_K3 = "moonshotai/kimi-k3"
OPENAI_GPT_LUNA = "gpt-6-luna"

# What each agent adapter runs when a model ref names no model.
CLAUDE_PLATFORM_AGENT = ModelRole(CLAUDE_PLATFORM, CLAUDE_OPUS)
BEDROCK_AGENT = ModelRole(BEDROCK, BEDROCK_CLAUDE_OPUS)
OPENROUTER_AGENT = ModelRole(OPENROUTER, OPENROUTER_CLAUDE_OPUS)

# Single-purpose features.
PRIMARY_IMAGE = ModelRole(BEDROCK, BEDROCK_CLAUDE_HAIKU)
# Expert profile matching and outreach emails.
RESEARCH_AI_BEDROCK = ModelRole(
    BEDROCK, BEDROCK_CLAUDE_HAIKU, "RESEARCH_AI_BEDROCK_MODEL_ID"
)
EXPERT_FINDER = ModelRole(OPENAI, OPENAI_GPT_LUNA)
PEER_REVIEW = ModelRole(
    BEDROCK, BEDROCK_CLAUDE_HAIKU, "AI_PEER_REVIEW_BEDROCK_MODEL_ID"
)
PEER_REVIEW_WEB_CONTEXT = ModelRole(
    OPENAI, OPENAI_GPT_LUNA, "AI_PEER_REVIEW_OPENAI_WEB_CONTEXT_MODEL"
)
SOCIAL_SHARE = ModelRole(OPENROUTER, OPENROUTER_KIMI_K3)

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
REFUSAL_FALLBACK = f"{OPENROUTER}:{OPENROUTER_KIMI}"


def refusal_fallback_ref() -> str | None:
    """The refusal fallback ref, or ``None`` when the setting turns moves off.

    An unset ``RESEARCH_AI_REFUSAL_FALLBACK_MODEL`` means the default; an empty
    one stops new moves, not ones already made.
    """
    value = getattr(settings, "RESEARCH_AI_REFUSAL_FALLBACK_MODEL", None)
    if value is None:
        return REFUSAL_FALLBACK
    return value or None
