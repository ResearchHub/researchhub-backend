"""Reviewed generation controls supported by each model family."""

import re
from dataclasses import dataclass

EFFORT_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
THINKING_MODES = ("adaptive", "disabled")
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0

CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
OPENROUTER_EFFORT_LEVELS = ("none", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelCapabilities:
    """Optional request controls one model accepts."""

    effort: tuple[str, ...] = ()
    thinking: tuple[str, ...] = ()
    temperature: bool = False
    # The model's output ceiling: a ``max_tokens`` above it is rejected
    # outright. ``None`` means unreviewed, not unlimited.
    max_output_tokens: int | None = None

    def as_dict(self) -> dict:
        # The model-picker payload: the controls a caller may choose.
        return {
            "effort": list(self.effort),
            "thinking": list(self.thinking),
            "temperature": self.temperature,
        }


# Control sets, shared by every model that accepts the same knobs. An output
# ceiling is never shared: each model states its own below.
_TEMPERATURE = ModelCapabilities(temperature=True)
_CLAUDE_EFFORT_TEMPERATURE = ModelCapabilities(
    effort=CLAUDE_EFFORT_LEVELS,
    temperature=True,
)
_CLAUDE_ADAPTIVE_TEMPERATURE = ModelCapabilities(
    effort=CLAUDE_EFFORT_LEVELS,
    thinking=THINKING_MODES,
    temperature=True,
)
_CLAUDE_ADAPTIVE = ModelCapabilities(
    effort=CLAUDE_EFFORT_LEVELS,
    thinking=THINKING_MODES,
)
_CLAUDE_MANDATORY_THINKING = ModelCapabilities(
    effort=CLAUDE_EFFORT_LEVELS,
    thinking=("adaptive",),
)
_OPENROUTER_REASONING = ModelCapabilities(
    effort=OPENROUTER_EFFORT_LEVELS,
    thinking=THINKING_MODES,
)
_OPENROUTER_GEMINI = ModelCapabilities(
    effort=("low", "medium", "high"),
    thinking=("adaptive",),
    temperature=True,
)
_OPENROUTER_GROK = ModelCapabilities(
    effort=("low", "medium", "high", "xhigh"),
    thinking=("adaptive",),
    temperature=True,
)
_OPENROUTER_MANDATORY_REASONING = ModelCapabilities(
    effort=("low", "high", "max"),
    thinking=("adaptive",),
    temperature=True,
)
_OPENROUTER_OPEN_WEIGHT = ModelCapabilities(
    effort=("none", "low", "high", "max"),
    thinking=THINKING_MODES,
    temperature=True,
)


def _model(controls: ModelCapabilities, max_output_tokens: int) -> ModelCapabilities:
    """One model: a shared control set plus that model's own output ceiling."""
    return ModelCapabilities(
        effort=controls.effort,
        thinking=controls.thinking,
        temperature=controls.temperature,
        max_output_tokens=max_output_tokens,
    )


# Ids arrive decorated: Bedrock inference-profile prefixes and ``-v1:0``
# suffixes, dated snapshots, Vertex ``@date``, OpenRouter ``:variant`` tags.
# Strip those, then a model resolves on its own id alone -- never on a longer
# id that merely contains it (``claude-opus-50`` is not Claude Opus 5).
_ID_PREFIXES = ("global.", "us.", "eu.", "apac.", "anthropic.")
_ID_DECORATIONS = re.compile(r"(-v\d+:\d+|[-@]\d{8}|:[a-z][a-z-]*)$")


def _normalized(model_id: str) -> str:
    """Reduce a platform-decorated id to the bare model id rules are keyed by."""
    mid = model_id.lower().strip()
    while True:
        stripped = _ID_DECORATIONS.sub("", mid)
        for prefix in _ID_PREFIXES:
            stripped = stripped.removeprefix(prefix)
        if stripped == mid:
            return mid
        mid = stripped


# One entry per model: its bare id, its controls, and the output ceiling its
# own docs state. A model absent here is unreviewed; adapters refuse to serve
# it rather than borrow another model's numbers.
_CLAUDE_MODELS = {
    "claude-haiku-4-5": _model(_TEMPERATURE, 64_000),
    "claude-sonnet-4-5": _model(_TEMPERATURE, 64_000),
    "claude-opus-4-5": _model(_CLAUDE_EFFORT_TEMPERATURE, 64_000),
    "claude-opus-4-6": _model(_CLAUDE_ADAPTIVE_TEMPERATURE, 128_000),
    "claude-sonnet-4-6": _model(_CLAUDE_ADAPTIVE_TEMPERATURE, 128_000),
    "claude-fable-5": _model(_CLAUDE_MANDATORY_THINKING, 128_000),
    "claude-mythos-5": _model(_CLAUDE_MANDATORY_THINKING, 128_000),
    "claude-opus-4-7": _model(_CLAUDE_ADAPTIVE, 128_000),
    "claude-opus-4-8": _model(_CLAUDE_ADAPTIVE, 128_000),
    "claude-opus-5": _model(_CLAUDE_ADAPTIVE, 128_000),
    "claude-sonnet-5": _model(_CLAUDE_ADAPTIVE, 128_000),
}

_OPENROUTER_MODELS = {
    "anthropic/claude-opus-5": _model(_OPENROUTER_REASONING, 128_000),
    "anthropic/claude-sonnet-5": _model(_OPENROUTER_REASONING, 128_000),
    "openai/gpt-5.6-sol": _model(_OPENROUTER_REASONING, 128_000),
    "openai/gpt-5.6-terra": _model(_OPENROUTER_REASONING, 128_000),
    "openai/gpt-5.6-luna": _model(_OPENROUTER_REASONING, 128_000),
    # No longer selectable, but retained for conversations pinned before removal.
    "google/gemini-3.1-pro-preview": _model(_OPENROUTER_GEMINI, 65_536),
    "google/gemini-3.7-flash": _model(_OPENROUTER_GEMINI, 65_536),
    "google/gemini-3.8-flash": _model(_OPENROUTER_GEMINI, 65_536),
    "x-ai/grok-4.6": _model(_OPENROUTER_GROK, 450_000),
    "z-ai/glm-5.3-flash": _model(_OPENROUTER_MANDATORY_REASONING, 131_072),
    "deepseek/deepseek-v4-flash-0731": _model(_OPENROUTER_OPEN_WEIGHT, 393_216),
    "deepseek/deepseek-v4-pro-0813": _model(_OPENROUTER_OPEN_WEIGHT, 384_000),
    "moonshotai/kimi-k3": _model(_OPENROUTER_OPEN_WEIGHT, 943_718),
}

# The Converse adapter currently exposes sampling only; Claude-specific effort
# and adaptive-thinking fields are implemented by Claude Platform.
_BEDROCK_MODELS = {
    "claude-haiku-4-5": _model(_TEMPERATURE, 64_000),
    "claude-sonnet-4-5": _model(_TEMPERATURE, 64_000),
}

_PROVIDER_MODELS = {
    "claude_platform": _CLAUDE_MODELS,
    "openrouter": _OPENROUTER_MODELS,
    "bedrock": _BEDROCK_MODELS,
}


def model_capabilities(provider: str, model_id: str) -> ModelCapabilities:
    """Return the reviewed controls for a provider/model pair."""
    models = _PROVIDER_MODELS.get(provider, {})
    return models.get(_normalized(model_id), ModelCapabilities())


def validate_generation_options(
    provider: str,
    model_id: str,
    *,
    effort: str | None = None,
    thinking: str | None = None,
    temperature: float | None = None,
) -> None:
    """Reject explicit controls the selected model cannot honor."""
    capabilities = model_capabilities(provider, model_id)
    label = f"{provider}:{model_id}"
    if effort is not None and effort not in capabilities.effort:
        raise ValueError(f"model {label!r} does not support effort {effort!r}")
    if thinking is not None and thinking not in capabilities.thinking:
        raise ValueError(f"model {label!r} does not support thinking {thinking!r}")
    if temperature is not None and not capabilities.temperature:
        raise ValueError(f"model {label!r} does not support temperature")
    if (
        provider == "claude_platform"
        and temperature is not None
        and capabilities.thinking
        and thinking != "disabled"
    ):
        raise ValueError(
            f"model {label!r} requires thinking='disabled' to use temperature"
        )
    if (
        provider == "openrouter"
        and thinking == "disabled"
        and effort
        not in (
            None,
            "none",
        )
    ):
        raise ValueError("OpenRouter cannot combine disabled thinking with effort")
    if provider == "openrouter" and thinking == "adaptive" and effort == "none":
        raise ValueError(
            "OpenRouter cannot combine adaptive thinking with effort='none'"
        )
    if (
        thinking == "disabled"
        and effort in ("xhigh", "max")
        and _normalized(model_id).endswith("claude-opus-5")
    ):
        raise ValueError(
            "Claude Opus 5 cannot use disabled thinking with xhigh or max effort"
        )
