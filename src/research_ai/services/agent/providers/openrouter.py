"""OpenRouter Chat Completions adapter.

OpenRouter fronts many model families behind the OpenAI Chat Completions wire
format, so this one adapter unlocks any OpenRouter-routable model for the
generator and the judge roster alike. It reuses the already-installed
``openai`` client pointed at the OpenRouter base URL and renders the neutral
agent types to/from the Chat Completions shape.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from openai import OpenAI

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Block,
    Message,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnUsage,
)

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Default generator model in OpenRouter's ``vendor/model`` slug format. Callers
# that want a different route pass ``model_id`` or use a prefixed model ref.
MODEL_ID = "anthropic/claude-opus-5"

# What ``max_tokens=None`` resolves to. Deliberately below the model's 128K
# ceiling: the completion is not streamed, so a longer emission would outlive
# the client read timeout and die whole. Raise only after moving to streaming.
MAX_OUTPUT_TOKENS = 32_768

# How much the model may deliberate and spend per turn. OpenRouter normalizes
# this across supported model families through ``reasoning.effort``. Keep the
# default aligned with the Claude Platform adapter so switching providers does
# not silently change the workflow's reasoning depth. ``""`` omits the option.
EFFORT = "low"

# Same guard as the Bedrock adapter: Opus 4.7+ and Fable reject sampling params
# (temperature/top_p) with a 400. OpenRouter forwards params to the upstream
# provider verbatim, so omit them for those models here too.
_NO_SAMPLING_PARAMS = (
    "opus-4-7",
    "opus-4-8",
    "opus-4.7",
    "opus-4.8",
    "opus-5",
    "sonnet-5",
    "fable",
    "mythos",
)


def _accepts_sampling_params(model_id: str) -> bool:
    mid = model_id.lower()
    return not any(tag in mid for tag in _NO_SAMPLING_PARAMS)


# Chat Completions ``finish_reason`` -> neutral ``StopReason``.
_FINISH_REASONS = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.CONTENT_FILTERED,
}


def _parse_arguments(raw: str | None) -> dict:
    """Parse a tool call's JSON ``arguments`` string; malformed -> ``{}``.

    The loop then dispatches the tool with empty input and the tool's own
    validation reports the problem back to the model as a retryable tool error,
    instead of the whole turn crashing on one bad argument string.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("OpenRouter tool arguments are not valid JSON: %.200r", raw)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _plain_dict(value: Any) -> dict:
    """Best-effort plain-dict copy of an SDK response object."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            result = dump(mode="json", exclude_none=True)
            return result if isinstance(result, dict) else {}
        except Exception:  # noqa: BLE001 - raw payload is debug-only
            return {}
    return dict(value) if isinstance(value, dict) else {}


class OpenRouterProvider(LLMProvider):
    """Adapts the neutral agent types to OpenRouter's Chat Completions API."""

    def __init__(self, *, client: Any = None, model_id: str | None = None):
        self.model_id = model_id or MODEL_ID
        self.effort = EFFORT
        if client is not None:
            self._client = client
        else:
            api_key = getattr(settings, "OPENROUTER_API_KEY", "") or ""
            self._client = (
                OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
                if api_key
                else None
            )

    # -- public surface ---------------------------------------------------

    def render_tools(self, tools: list[Tool]) -> list[dict]:
        """Render tools to the Chat Completions function-tool list."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int | None,
        temperature: float,
        before_retry: Callable[[], None] | None = None,
    ) -> AssistantTurn:
        if self._client is None:
            raise ProviderError(
                "OPENROUTER_API_KEY is not configured; cannot call OpenRouter."
            )
        kwargs: dict = {
            "model": self.model_id,
            "messages": self._render_messages(system_prompt, messages),
            "max_tokens": MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens,
        }
        if _accepts_sampling_params(self.model_id):
            kwargs["temperature"] = temperature
        if rendered_tools:
            kwargs["tools"] = rendered_tools
        if self.effort:
            # ``reasoning`` is an OpenRouter extension rather than an OpenAI
            # Chat Completions argument, so the OpenAI client forwards it via
            # ``extra_body``.
            kwargs["extra_body"] = {"reasoning": {"effort": self.effort}}

        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.exception("OpenRouter complete failed")
            raise ProviderError(f"OpenRouter complete failed: {e}") from e
        latency_ms = int((time.perf_counter() - started) * 1000)

        self._log_usage(response)
        return self._parse_turn(response, latency_ms=latency_ms)

    # -- private helpers --------------------------------------------------

    def _render_messages(
        self, system_prompt: str, messages: list[Message]
    ) -> list[dict]:
        rendered: list[dict] = [{"role": "system", "content": system_prompt}]
        for message in messages:
            if message.role == "assistant":
                rendered.append(self._render_assistant(message))
                continue
            # User-side turns: each tool result becomes its own ``tool`` message
            # keyed by ``tool_call_id`` (the id-correlation invariant), emitted
            # before any plain text so they directly follow the assistant
            # message that issued the calls, as the wire format requires.
            texts: list[str] = []
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    # No error flag on tool messages in this wire format; the
                    # error payload inside ``content`` is what the model sees.
                    rendered.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.tool_use_id,
                            "content": json.dumps(block.content),
                        }
                    )
                elif isinstance(block, TextBlock):
                    texts.append(block.text)
                else:
                    raise TypeError(f"unrenderable user block: {block!r}")
            if texts:
                rendered.append({"role": "user", "content": "".join(texts)})
        return rendered

    def _render_assistant(self, message: Message) -> dict:
        texts: list[str] = []
        reasoning_details: list[dict] = []
        tool_calls: list[dict] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                texts.append(block.text)
            elif isinstance(block, ThinkingBlock):
                # OpenRouter requires complete reasoning details to be replayed
                # unchanged when a reasoning model continues after a tool call.
                reasoning_details.append(dict(block.data))
            elif isinstance(block, ToolUseBlock):
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input),
                        },
                    }
                )
            else:
                raise TypeError(f"unrenderable assistant block: {block!r}")
        rendered: dict = {"role": "assistant", "content": "".join(texts) or None}
        if reasoning_details:
            rendered["reasoning_details"] = reasoning_details
        if tool_calls:
            rendered["tool_calls"] = tool_calls
        return rendered

    def _log_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        logger.info(
            "openrouter usage: input=%s cached=%s output=%s",
            getattr(usage, "prompt_tokens", None),
            self._cached_tokens(usage),
            getattr(usage, "completion_tokens", None),
        )

    def _parse_turn(
        self, response: Any, *, latency_ms: int | None = None
    ) -> AssistantTurn:
        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        if message is None:
            raise ProviderError("Invalid OpenRouter response: missing message")

        text_blocks: list[TextBlock] = []
        content = getattr(message, "content", None)
        if content:
            text_blocks.append(TextBlock(text=content))

        thinking_blocks = [
            ThinkingBlock(data=payload)
            for detail in getattr(message, "reasoning_details", None) or []
            if (payload := _plain_dict(detail))
        ]

        tool_calls: list[ToolUseBlock] = []
        for call in getattr(message, "tool_calls", None) or []:
            function = getattr(call, "function", None)
            if function is None:
                continue
            tool_calls.append(
                ToolUseBlock(
                    id=call.id,
                    name=function.name,
                    input=_parse_arguments(function.arguments),
                )
            )

        stop_reason = _FINISH_REASONS.get(
            getattr(choices[0], "finish_reason", None), StopReason.OTHER
        )
        # Some routes report ``stop`` even when the turn carries tool calls;
        # the loop keys off TOOL_USE, so present calls win.
        if tool_calls and stop_reason == StopReason.END_TURN:
            stop_reason = StopReason.TOOL_USE

        content_blocks: list[Block] = [
            *thinking_blocks,
            *text_blocks,
            *tool_calls,
        ]
        return AssistantTurn(
            text_blocks=text_blocks,
            thinking_blocks=thinking_blocks,
            tool_calls=tool_calls,
            content_blocks=content_blocks,
            stop_reason=stop_reason,
            raw=_plain_dict(response),
            usage=self._parse_usage(response),
            latency_ms=latency_ms,
        )

    def _parse_usage(self, response: Any) -> TurnUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        return TurnUsage(
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            cache_read_tokens=self._cached_tokens(usage),
        )

    @staticmethod
    def _cached_tokens(usage: Any) -> int | None:
        details = getattr(usage, "prompt_tokens_details", None)
        if details is None:
            return None
        return getattr(details, "cached_tokens", None)
