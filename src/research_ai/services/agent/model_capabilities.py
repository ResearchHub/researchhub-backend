"""Reviewed generation controls supported by each model family."""

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


# One row per model -- id tags, controls, and the output ceiling its own docs
# state. A model absent here is unreviewed and the adapters refuse to serve it.
_CLAUDE_RULES = (
    (("haiku-4-5", "haiku-4.5"), _model(_TEMPERATURE, 64_000)),
    (("sonnet-4-5", "sonnet-4.5"), _model(_TEMPERATURE, 64_000)),
    (("opus-4-5", "opus-4.5"), _model(_CLAUDE_EFFORT_TEMPERATURE, 64_000)),
    (("opus-4-6", "opus-4.6"), _model(_CLAUDE_ADAPTIVE_TEMPERATURE, 128_000)),
    (("sonnet-4-6", "sonnet-4.6"), _model(_CLAUDE_ADAPTIVE_TEMPERATURE, 128_000)),
    (("fable",), _model(_CLAUDE_MANDATORY_THINKING, 128_000)),
    (("mythos",), _model(_CLAUDE_MANDATORY_THINKING, 128_000)),
    (("opus-4-7", "opus-4.7"), _model(_CLAUDE_ADAPTIVE, 128_000)),
    (("opus-4-8", "opus-4.8"), _model(_CLAUDE_ADAPTIVE, 128_000)),
    (("opus-5",), _model(_CLAUDE_ADAPTIVE, 128_000)),
    (("sonnet-5",), _model(_CLAUDE_ADAPTIVE, 128_000)),
)

_OPENROUTER_RULES = (
    (("anthropic/claude-opus-5",), _model(_OPENROUTER_REASONING, 128_000)),
    (("anthropic/claude-sonnet-5",), _model(_OPENROUTER_REASONING, 128_000)),
    (("openai/gpt-5.6-sol",), _model(_OPENROUTER_REASONING, 128_000)),
    (("openai/gpt-5.6-terra",), _model(_OPENROUTER_REASONING, 128_000)),
    (("openai/gpt-5.6-luna",), _model(_OPENROUTER_REASONING, 128_000)),
    (("google/gemini-3.1-pro-preview",), _model(_OPENROUTER_GEMINI, 65_536)),
    (("google/gemini-3.7-flash",), _model(_OPENROUTER_GEMINI, 65_536)),
    (("x-ai/grok-4.6",), _model(_OPENROUTER_GROK, 450_000)),
    (("deepseek/deepseek-v4-pro-0813",), _model(_OPENROUTER_OPEN_WEIGHT, 384_000)),
    (("moonshotai/kimi-k3",), _model(_OPENROUTER_OPEN_WEIGHT, 943_718)),
)

# The Converse adapter currently exposes sampling only; Claude-specific effort
# and adaptive-thinking fields are implemented by Claude Platform.
_BEDROCK_RULES = (
    (("haiku-4-5", "haiku-4.5"), _model(_TEMPERATURE, 64_000)),
    (("sonnet-4-5", "sonnet-4.5"), _model(_TEMPERATURE, 64_000)),
)


def model_capabilities(provider: str, model_id: str) -> ModelCapabilities:
    """Return the reviewed controls for a provider/model pair."""
    mid = model_id.lower()
    if provider == "openrouter":
        rules = _OPENROUTER_RULES
    elif provider == "claude_platform":
        rules = _CLAUDE_RULES
    elif provider == "bedrock":
        rules = _BEDROCK_RULES
    else:
        return ModelCapabilities()
    for tags, capabilities in rules:
        if any(tag in mid for tag in tags):
            return capabilities
    return ModelCapabilities()


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
        and "opus-5" in model_id.lower()
    ):
        raise ValueError(
            "Claude Opus 5 cannot use disabled thinking with xhigh or max effort"
        )
