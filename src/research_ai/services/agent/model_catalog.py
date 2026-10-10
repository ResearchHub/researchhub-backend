"""Model support and the visible picker catalog for agent workflows.

The notebook assistant and proposal drafting accept a curated allowlist of
provider-prefixed model refs (the registry's ``[<provider>:]<model id>``
grammar), so request input can never route to an arbitrary model id. The
picker lists six current models; older supported models remain valid for
existing conversations and explicit model refs without appearing in that list.

Claude models are served through Claude Platform for its first-party features
(native web search, adaptive thinking, prompt caching); other vendors go
through OpenRouter. The hidden refs span Claude Platform, OpenRouter, and
Bedrock.

The catalog is not credential-gated. Provider keys are configured on the
Celery workers that execute turns, not on the API process that serves this
listing, so checking them here would hide models that run fine; each provider
raises on missing credentials where they are actually used. The configured
generator default is listed too, even when it falls outside the catalog,
unless it is hidden. All selections require reviewed pricing; tier-aware
default resolution falls back to a priced model.
"""

from dataclasses import dataclass

from research_ai.services.agent.model_capabilities import (
    ModelCapabilities,
    model_capabilities,
)
from research_ai.services.agent.model_pricing import model_pricing
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
        ref=f"{CLAUDE_PLATFORM}:claude-opus-5-5",
        label="Claude Opus 5.5",
        description="Anthropic's newer model for long-running research and drafting.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:openai/gpt-6.1-sol",
        label="GPT-6.1 Sol",
        description="OpenAI's model for complex analysis and agent workflows.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:x-ai/grok-4.7",
        label="Grok 4.7",
        description="xAI's flagship for agentic tasks and knowledge work.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:meta/muse-spark-1.3",
        label="Muse Spark 1.3",
        description="Meta's reasoning model for long multi-step work at low cost.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:moonshotai/kimi-k3",
        label="Kimi K3",
        description="Moonshot's frontier open-weight model.",
    ),
    ModelOption(
        ref=f"{OPENROUTER}:xiaomi/mimo-v2.6-pro",
        label="MiMo-V2.6-Pro",
        description="Xiaomi's flagship open-weight model at very low cost.",
    ),
)

# Keep older refs supported, while preventing provider defaults from
# reintroducing them into the picker.
_HIDDEN_REFS = frozenset(
    {
        f"{CLAUDE_PLATFORM}:claude-opus-5",
        f"{CLAUDE_PLATFORM}:claude-sonnet-5",
        "bedrock:us.anthropic.claude-opus-5",
        f"{OPENROUTER}:anthropic/claude-opus-5",
        f"{OPENROUTER}:openai/gpt-6-sol",
        f"{OPENROUTER}:openai/gpt-6-luna",
        f"{OPENROUTER}:openai/gpt-5.6-sol",
        f"{OPENROUTER}:openai/gpt-5.6-terra",
        f"{OPENROUTER}:openai/gpt-5.6-luna",
        f"{OPENROUTER}:google/gemini-3.8-flash",
        f"{OPENROUTER}:x-ai/grok-4.6",
        f"{OPENROUTER}:z-ai/glm-5.3-flash",
        f"{OPENROUTER}:deepseek/deepseek-v4-flash-0731",
        f"{OPENROUTER}:deepseek/deepseek-v4-pro-0813",
        f"{OPENROUTER}:qwen/qwen3.8-max-0902",
    }
)


def available_models() -> list[ModelOption]:
    """The model listing, including the configured generator default.

    The configured generator default is prepended when the catalog does not
    already carry it, unless the default is hidden. An unpriced default
    stays visible for diagnostics but cannot be selected; tier default
    resolution chooses a priced alternative.
    """
    options = list(_CATALOG)
    default_ref = default_model_ref()
    if default_ref not in _HIDDEN_REFS and not any(
        option.ref == default_ref for option in options
    ):
        options.insert(
            0,
            ModelOption(ref=default_ref, label=split_model_ref(default_ref)[1] or ""),
        )
    return options


def default_model_ref() -> str:
    """What runs when the user picks nothing: the configured generator."""
    return generator_model_ref()


def supported_model_refs() -> frozenset[str]:
    """Configured refs, including hidden ones, subject to reviewed pricing."""
    return (
        frozenset(option.ref for option in _CATALOG)
        | _HIDDEN_REFS
        | {default_model_ref()}
    )


def validate_model_ref(value: str | None) -> str | None:
    """Normalize a user-supplied model ref against the supported allowlist.

    ``None``/blank means "no selection" and returns ``None`` (callers fall
    back to the tier default). A bare ref canonicalizes onto the generator
    provider. Hidden older models remain usable with explicit refs.
    """
    if value is None or not value.strip():
        return None
    requested = _canonical(value.strip())
    if requested not in supported_model_refs():
        raise ValueError(f"unknown model: {value.strip()!r}")
    provider, model_id = split_model_ref(requested)
    if model_pricing(provider, model_id or "") is None:
        raise ValueError(f"model {requested!r} has no reviewed pricing")
    return requested


def _canonical(ref: str) -> str:
    provider, model_id = split_model_ref(ref)
    return f"{provider}:{model_id or ''}"
