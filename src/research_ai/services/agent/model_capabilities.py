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

    def as_dict(self) -> dict:
        return {
            "effort": list(self.effort),
            "thinking": list(self.thinking),
            "temperature": self.temperature,
        }


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

_CLAUDE_RULES = (
    (("haiku-4-5", "haiku-4.5", "sonnet-4-5", "sonnet-4.5"), _TEMPERATURE),
    (("opus-4-5", "opus-4.5"), _CLAUDE_EFFORT_TEMPERATURE),
    (
        ("opus-4-6", "opus-4.6", "sonnet-4-6", "sonnet-4.6"),
        _CLAUDE_ADAPTIVE_TEMPERATURE,
    ),
    (("fable", "mythos"), _CLAUDE_MANDATORY_THINKING),
    (
        (
            "opus-4-7",
            "opus-4.7",
            "opus-4-8",
            "opus-4.8",
            "opus-5",
            "sonnet-5",
        ),
        _CLAUDE_ADAPTIVE,
    ),
)

_OPENROUTER_RULES = (
    (
        ("anthropic/claude-opus-5", "anthropic/claude-sonnet-5"),
        ModelCapabilities(
            effort=("none", "low", "medium", "high", "xhigh", "max"),
            thinking=THINKING_MODES,
        ),
    ),
    (
        ("openai/gpt-5.6-sol", "openai/gpt-5.6-terra", "openai/gpt-5.6-luna"),
        ModelCapabilities(
            effort=OPENROUTER_EFFORT_LEVELS,
            thinking=THINKING_MODES,
        ),
    ),
    (
        ("google/gemini-3.1-pro-preview", "google/gemini-3.7-flash"),
        ModelCapabilities(
            effort=("low", "medium", "high"),
            thinking=("adaptive",),
            temperature=True,
        ),
    ),
    (
        ("x-ai/grok-4.6",),
        ModelCapabilities(
            effort=("low", "medium", "high", "xhigh"),
            thinking=("adaptive",),
            temperature=True,
        ),
    ),
    (
        ("deepseek/deepseek-v4-pro-0813", "moonshotai/kimi-k3"),
        ModelCapabilities(
            effort=("none", "low", "high", "max"),
            thinking=THINKING_MODES,
            temperature=True,
        ),
    ),
)


def model_capabilities(provider: str, model_id: str) -> ModelCapabilities:
    """Return the reviewed controls for a provider/model pair."""
    mid = model_id.lower()
    if provider == "openrouter":
        rules = _OPENROUTER_RULES
    elif provider == "claude_platform":
        rules = _CLAUDE_RULES
    elif provider == "bedrock":
        # The Converse adapter currently exposes sampling only; Claude-specific
        # effort and adaptive-thinking fields are implemented by Claude Platform.
        rules = (
            (
                ("haiku-4-5", "haiku-4.5", "sonnet-4-5", "sonnet-4.5"),
                _TEMPERATURE,
            ),
        )
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
