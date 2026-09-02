"""The user-selectable model catalog for agent workflows.

The notebook assistant and the proposal-drafting run let the user pick the
model a turn/run generates with. This module owns what may be picked: a
curated allowlist of provider-prefixed model refs (the registry's
``[<provider>:]<model id>`` grammar), so request input can never route to an
arbitrary model id. Adding, removing, or re-routing a model is an edit to
``_CATALOG`` below.

The catalog lists each model once, on the provider that serves it best:
Anthropic models through Claude Platform (first-party features -- native web
search, adaptive thinking, prompt caching) and every other family through
OpenRouter. Bedrock refs are equally valid entries; they are just not listed,
since they would duplicate the Anthropic entries under a second name.

The catalog is not credential-gated. Provider keys are configured on the
Celery workers that execute turns, not on the API process that serves this
listing, so checking them here would hide models that run fine; each provider
raises on missing credentials where they are actually used. The configured
generator default is listed too, even when it falls outside the catalog,
because it is what runs when the user picks nothing.
"""

from dataclasses import dataclass

from research_ai.services.agent.model_capabilities import (
    ModelCapabilities,
    model_capabilities,
)
from research_ai.services.agent.providers.registry import (
    CLAUDE_PLATFORM,
    OPENROUTER,
    generator_model_ref,
    split_model_ref,
)


@dataclass(frozen=True)
class ModelOption:
    """One selectable model: a canonical prefixed ref plus display copy."""

    ref: str
    label: str
    description: str = ""

    @property
    def provider(self) -> str:
        return split_model_ref(self.ref)[0]

    @property
    def capabilities(self) -> ModelCapabilities:
        provider, model_id = split_model_ref(self.ref)
        return model_capabilities(provider, model_id or "")


_CATALOG: tuple[ModelOption, ...] = (
    ModelOption(
        ref=f"{CLAUDE_PLATFORM}:claude-opus-5",
        label="Claude Opus 5",
        description="Anthropic's flagship; strongest on agentic research and drafting.",
    ),
    ModelOption(
        ref=f"{CLAUDE_PLATFORM}:claude-sonnet-5",
        label="Claude Sonnet 5",
        description="Anthropic's balanced model; near-flagship quality, faster.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:openai/gpt-5.6-sol",
        label="GPT-5.6 Sol",
        description="OpenAI's flagship generalist.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:openai/gpt-5.6-terra",
        label="GPT-5.6 Terra",
        description="OpenAI's balanced model for everyday research and drafting.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:openai/gpt-5.6-luna",
        label="GPT-5.6 Luna",
        description="OpenAI's fast, cost-efficient model.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:google/gemini-3.1-pro-preview",
        label="Gemini 3.1 Pro",
        description="Google's frontier reasoning model.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:google/gemini-3.7-flash",
        label="Gemini 3.7 Flash",
        description="Google's fast, low-cost model.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:x-ai/grok-4.6",
        label="Grok 4.6",
        description="xAI's frontier model.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:deepseek/deepseek-v4-pro-0813",
        label="DeepSeek V4 Pro",
        description="DeepSeek's frontier open-weight model.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:moonshotai/kimi-k3",
        label="Kimi K3",
        description="Moonshot's frontier open-weight model.",
    ),
)


def available_models() -> list[ModelOption]:
    """The models a user may select, generator default first-class.

    The configured generator default is prepended when the catalog does not
    already carry it, so "what runs by default" is always also a legal
    explicit choice.
    """
    options = list(_CATALOG)
    default_ref = default_model_ref()
    if not any(option.ref == default_ref for option in options):
        options.insert(
            0,
            ModelOption(ref=default_ref, label=split_model_ref(default_ref)[1] or ""),
        )
    return options


def default_model_ref() -> str:
    """What runs when the user picks nothing: the configured generator."""
    return generator_model_ref()


def validate_model_ref(value: str | None) -> str | None:
    """Normalize a user-supplied model selection against the catalog.

    ``None``/blank means "no selection" and returns ``None`` (callers fall
    back to the generator default). A ref matching a selectable model --
    prefixed or bare, since a bare ref canonicalizes onto the generator
    provider -- returns that model's canonical prefixed ref. Anything else
    raises ``ValueError``.
    """
    if value is None or not value.strip():
        return None
    requested = _canonical(value.strip())
    for option in available_models():
        if _canonical(option.ref) == requested:
            return option.ref
    raise ValueError(f"unknown model: {value.strip()!r}")


def _canonical(ref: str) -> str:
    provider, model_id = split_model_ref(ref)
    return f"{provider}:{model_id or ''}"
