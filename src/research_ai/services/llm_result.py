"""Compatibility result for legacy text-returning LLM integrations."""

from typing import Any

from research_ai.services.agent.types import TurnUsage


class LLMTextResult(str):
    """A string-compatible result that retains the response's token usage."""

    text: str
    usage: TurnUsage | None

    def __new__(cls, text: str, usage: TurnUsage | None = None):
        value = str(text or "")
        result = super().__new__(cls, value)
        result.text = value
        result.usage = usage
        return result


def integer(value: Any) -> int | None:
    """Accept real integer counters without coercing mocks or malformed values."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def bedrock_usage(response: dict) -> TurnUsage | None:
    payload = response.get("usage") or {}
    usage = TurnUsage(
        input_tokens=integer(payload.get("inputTokens")),
        output_tokens=integer(payload.get("outputTokens")),
        cache_read_tokens=integer(payload.get("cacheReadInputTokens")),
        cache_write_tokens=integer(payload.get("cacheWriteInputTokens")),
    )
    return (
        usage if any(value is not None for value in usage.__dict__.values()) else None
    )


def openai_usage(response: Any) -> TurnUsage | None:
    payload = getattr(response, "usage", None)
    if payload is None:
        return None
    input_tokens = integer(
        getattr(payload, "input_tokens", None)
        or getattr(payload, "prompt_tokens", None)
    )
    output_tokens = integer(
        getattr(payload, "output_tokens", None)
        or getattr(payload, "completion_tokens", None)
    )
    details = getattr(payload, "input_tokens_details", None) or getattr(
        payload, "prompt_tokens_details", None
    )
    cached = integer(getattr(details, "cached_tokens", None)) if details else None
    usage = TurnUsage(input_tokens, output_tokens, cached, None)
    return (
        usage if any(value is not None for value in usage.__dict__.values()) else None
    )
