"""OpenRouter Chat Completions adapter.

OpenRouter fronts many model families behind the OpenAI Chat Completions wire
format, so this one adapter unlocks any OpenRouter-routable model for the
generator and the judge roster alike. It reuses the already-installed
``openai`` client pointed at the OpenRouter base URL and renders the neutral
agent types to/from the Chat Completions shape. Agent turns
(``complete_with_events``) are streamed; one-shot ``complete`` calls are not.
"""

import base64
import json
import logging
import time
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx
import openai
from django.conf import settings
from openai import OpenAI
from openai.types.chat import ChatCompletion

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.images import (
    ImageLoader,
    RequestImages,
    image_placeholder,
)
from research_ai.services.agent.model_capabilities import model_capabilities
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Block,
    ImageBlock,
    Message,
    ProviderStreamEvent,
    StopReason,
    StreamReset,
    TextBlock,
    TextStreamDelta,
    ThinkingBlock,
    ThinkingStreamDelta,
    ToolInputStreamDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseStreamStart,
    TurnUsage,
)
from research_ai.services.llm_models import OPENROUTER_AGENT

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Default generator model (see ``llm_models``), in OpenRouter's
# ``vendor/model`` slug format. Callers that want a different route pass
# ``model_id`` or use a prefixed model ref.
MODEL_ID = OPENROUTER_AGENT.model_id

# What ``max_tokens=None`` resolves to: a spend budget, not a model limit.
# Deliberately below every routed model's ceiling because ``complete`` is not
# streamed, so a longer emission would outlive the client read timeout and die
# whole. Agent turns stream; raise only once ``complete`` does too. The model's
# own ceiling (``ModelCapabilities.max_output_tokens``) clamps this and anything
# a caller asks for.
MAX_OUTPUT_TOKENS = 32_768

# How much the model may deliberate and spend per turn. OpenRouter normalizes
# this across supported model families through ``reasoning.effort``. Keep the
# default aligned with the Claude Platform adapter so switching providers does
# not silently change the workflow's reasoning depth. ``""`` omits the option.
EFFORT = "low"

# Upstream image caps differ and are not all published; this is the tightest
# known one (5 MB in base64).
MAX_IMAGE_BYTES = 5 * 1024 * 1024 * 3 // 4
# Likewise for a whole request: Bedrock's 20 MB, less the third base64 adds
# and room for the conversation's text.
MAX_REQUEST_IMAGE_BYTES = 10 * 1024 * 1024

# Shown before a tool result's images, which travel in a user message after
# every result of the turn; a model may not see ids, so it gets the position too.
_TOOL_IMAGES_NOTE = "[Images returned by tool result {position} above (id {id}).]\n"

# OpenAI supports function calling for these models via Chat Completions only
# with reasoning effort set to none. This adapter uses Chat Completions.
_GPT6_CHAT_TOOLS_MODELS = frozenset({"openai/gpt-6-sol", "openai/gpt-6-luna"})


# Statuses worth repeating unchanged: timeouts, races, rate limits, and every
# server-side failure. Auth/config/invalid-request statuses fail identically
# on every attempt.
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})


def _is_retryable_error(error: Exception) -> bool:
    """Whether this SDK failure is transient rather than a fault of the request."""
    if isinstance(error, openai.APIConnectionError):
        return True
    if isinstance(error, openai.APIStatusError):
        status = error.status_code
        return status in _RETRYABLE_STATUS_CODES or status >= 500
    return False


def _stream_error_body(error: Exception) -> dict | None:
    """The error body OpenRouter sent mid-stream, or ``None``.

    Once a stream has started its status is a 200, so OpenRouter reports a
    later failure as a chunk holding an ``error`` object, which the SDK raises
    as a bare ``APIError`` carrying that object. It is the streamed form of a
    200 whose body holds an error, and is classified the same way.
    """
    if not isinstance(error, openai.APIError) or isinstance(
        error, openai.APIStatusError | openai.APIConnectionError
    ):
        return None
    return error.body if isinstance(error.body, dict) else None


# 403 ``error_type``s for a request the model or a content filter declined.
_REFUSAL_ERROR_TYPES = frozenset({"refusal", "content_policy_violation"})

# How much of an unexplained response body a failure's message carries.
_MAX_ERROR_SUMMARY_CHARS = 200

# Repeats of a request whose response arrived with no usable choice.
_EMPTY_RESPONSE_RETRIES = 1


class _EmptyResponseError(ProviderError):
    """A 200 that carried no usable choice, or a stream cut off before its end.

    Its own type so ``complete`` can repeat the request the SDK will not,
    while every caller outside this adapter still sees a ``ProviderError``.
    """


def _is_refusal(metadata: Any) -> bool:
    """Whether an OpenRouter error's ``metadata`` reports a refusal."""
    if not isinstance(metadata, dict):
        return False
    if metadata.get("error_type") in _REFUSAL_ERROR_TYPES:
        return True
    # A moderation flag carries the flagged text instead of an error type.
    return "flagged_input" in metadata


def _refusal_error(error: Exception) -> dict | None:
    """The error body when OpenRouter reports a refusal or flagged input."""
    if not isinstance(error, openai.PermissionDeniedError):
        return None
    body = error.body if isinstance(error.body, dict) else {}
    return body if _is_refusal(body.get("metadata")) else None


def _body_error(body: dict) -> dict:
    """The ``error`` object a 200 response carries, or ``{}``."""
    error = body.get("error")
    return error if isinstance(error, dict) else {}


def _body_error_retryable(error: dict) -> bool:
    """Whether an error OpenRouter put in a 200 body is worth repeating.

    The body mirrors HTTP status codes in ``code``, so the same split applies
    as for a raised status error. A body that reports no code explained
    nothing -- the case this classifies most often -- and an identical request
    has no established reason to fail the same way, so it is worth one.
    """
    code = error.get("code")
    if not isinstance(code, int):
        return True
    return code in _RETRYABLE_STATUS_CODES or code >= 500


def _body_error_summary(error: dict) -> str:
    """An unexplained response's own account of itself, for the failure."""
    if not error:
        return "no error reported"
    summary = f"code={error.get('code')} {error.get('message') or 'no message'}"
    return summary[:_MAX_ERROR_SUMMARY_CHARS]


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
    except TypeError, ValueError:
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


# Reasoning-detail fields a stream splits across chunks of the same detail.
_CONCATENATED_DETAIL_FIELDS = frozenset({"text", "summary", "data"})

# Reasoning-detail types a person can read; others (``reasoning.encrypted``)
# are opaque continuation state and are never shown.
_READABLE_DETAIL_FIELDS = {"reasoning.text": "text", "reasoning.summary": "summary"}


def _readable_reasoning(detail: dict) -> str:
    """The text of a reasoning-detail fragment that may be shown, or ``""``."""
    value = detail.get(_READABLE_DETAIL_FIELDS.get(detail.get("type"), ""))
    return value if isinstance(value, str) else ""


class _StreamedCompletion:
    """Folds a Chat Completions stream back into the completion it streamed.

    The result has the shape a non-streamed request returns, so a streamed turn
    is parsed, billed and classified by the same code as one from ``complete``.
    Chunks are reported to ``on_event`` as they arrive. Chat Completions deltas
    carry no content-block index, so each block -- the reasoning, the text, and
    every tool call -- gets one when it first appears.
    """

    def __init__(self, on_event: Callable[[ProviderStreamEvent], None] | None):
        self._on_event = on_event
        self._body: dict = {}
        self._choice: dict | None = None
        self._content: list[str] = []
        self._reasoning: list[str] = []
        self._details: dict[Any, dict] = {}
        self._tool_calls: dict[int, dict] = {}
        self._started_tools: set[int] = set()
        self._block_indices: dict[Any, int] = {}

    def add(self, chunk: Any) -> None:
        data = _plain_dict(chunk)
        for key in ("id", "created", "model", "provider", "system_fingerprint"):
            if key in data:
                self._body[key] = data[key]
        if data.get("usage"):
            # Sent on the last chunk, which carries no choice.
            self._body["usage"] = data["usage"]
        for choice in data.get("choices") or []:
            if choice.get("index", 0) != 0:
                continue
            if self._choice is None:
                self._choice = {"index": 0, "finish_reason": None}
            if choice.get("finish_reason"):
                self._choice["finish_reason"] = choice["finish_reason"]
            self._add_delta(choice.get("delta") or {})

    @property
    def finished(self) -> bool:
        """Whether the choice, if any arrived, reached a finish reason.

        A stream with no choice at all is the streamed form of an empty 200
        and is reported as one by the parser, so only a started choice counts.
        """
        return self._choice is None or self._choice["finish_reason"] is not None

    def completion(self) -> ChatCompletion:
        body: dict = {
            "id": "",
            "created": 0,
            "model": "",
            **self._body,
            "object": "chat.completion",
            "choices": [],
        }
        if self._choice is not None:
            message: dict = {
                "role": "assistant",
                "content": "".join(self._content) or None,
            }
            if self._reasoning:
                message["reasoning"] = "".join(self._reasoning)
            if self._details:
                message["reasoning_details"] = list(self._details.values())
            if self._tool_calls:
                message["tool_calls"] = [
                    call for _, call in sorted(self._tool_calls.items())
                ]
            body["choices"] = [{**self._choice, "message": message}]
        # ``construct`` builds the nested SDK models without validating, as the
        # SDK does for a response, so OpenRouter's extra fields survive.
        return ChatCompletion.construct(**body)

    def _add_delta(self, delta: dict) -> None:
        content = delta.get("content")
        if isinstance(content, str) and content:
            self._content.append(content)
            self._emit(TextStreamDelta(block_index=self._index("text"), text=content))

        reasoning = delta.get("reasoning")
        reasoning = reasoning if isinstance(reasoning, str) else ""
        if reasoning:
            self._reasoning.append(reasoning)
        details = [
            detail
            for detail in delta.get("reasoning_details") or []
            if isinstance(detail, dict)
        ]
        for detail in details:
            self._add_detail(detail)
        readable = "".join(map(_readable_reasoning, details)) or reasoning
        if readable:
            self._emit(
                ThinkingStreamDelta(block_index=self._index("thinking"), text=readable)
            )

        for call in delta.get("tool_calls") or []:
            if isinstance(call, dict):
                self._add_tool_call(call)

    def _add_detail(self, detail: dict) -> None:
        """Merge one reasoning-detail fragment into the detail it continues."""
        key = detail.get("index")
        if not isinstance(key, int):
            key = ("unindexed", len(self._details))
        merged = self._details.setdefault(key, {})
        for field, value in detail.items():
            previous = merged.get(field)
            if (
                field in _CONCATENATED_DETAIL_FIELDS
                and isinstance(previous, str)
                and isinstance(value, str)
            ):
                merged[field] = previous + value
            else:
                merged[field] = value

    def _add_tool_call(self, call: dict) -> None:
        index = call.get("index")
        if not isinstance(index, int):
            index = len(self._tool_calls)
        entry = self._tool_calls.setdefault(
            index,
            {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
        )
        # A route may split the id and the name across deltas too, so every
        # string field is concatenated, as the SDK's own accumulator does.
        call_id = call.get("id")
        if isinstance(call_id, str) and call_id:
            entry["id"] = (entry["id"] or "") + call_id
        function = call.get("function") or {}
        name = function.get("name")
        if isinstance(name, str) and name:
            entry["function"]["name"] += name
        arguments = function.get("arguments")
        arguments = arguments if isinstance(arguments, str) else ""
        entry["function"]["arguments"] += arguments
        if not arguments:
            # The name may still be arriving, so the draft opens with the
            # first fragment of its arguments.
            return

        block_index = self._index(("tool", index))
        if index not in self._started_tools:
            if not entry["function"]["name"]:
                # Arguments before the name are kept and shown once it arrives.
                return
            self._started_tools.add(index)
            self._emit(
                ToolUseStreamStart(
                    block_index=block_index, name=entry["function"]["name"]
                )
            )
            arguments = entry["function"]["arguments"]
        if arguments:
            self._emit(
                ToolInputStreamDelta(block_index=block_index, partial_json=arguments)
            )

    def _index(self, block: Any) -> int:
        return self._block_indices.setdefault(block, len(self._block_indices))

    def _emit(self, event: ProviderStreamEvent) -> None:
        if self._on_event is not None:
            self._on_event(event)


class OpenRouterProvider(LLMProvider):
    """Adapts the neutral agent types to OpenRouter's Chat Completions API."""

    def __init__(
        self,
        *,
        client: Any = None,
        model_id: str | None = None,
        effort: str | None = None,
        thinking: str | None = None,
        image_loader: ImageLoader | None = None,
    ):
        self.model_id = model_id or MODEL_ID
        self.image_loader = image_loader
        capabilities = model_capabilities("openrouter", self.model_id)
        if effort is not None:
            self.effort = effort
        elif self.model_id in _GPT6_CHAT_TOOLS_MODELS:
            self.effort = "none"
        else:
            self.effort = EFFORT if EFFORT in capabilities.effort else ""
        self.thinking = thinking
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
        on_usage: Callable[[TurnUsage], None] | None = None,
    ) -> AssistantTurn:
        self._require_client()
        kwargs = self._request_kwargs(
            system_prompt=system_prompt,
            messages=messages,
            rendered_tools=rendered_tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return self._retrying_empty(
            lambda: self._request_turn(kwargs, on_usage), before_retry
        )

    def complete_with_events(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int | None,
        temperature: float,
        on_event: Callable[[ProviderStreamEvent], None] | None = None,
        before_retry: Callable[[], None] | None = None,
        on_usage: Callable[[TurnUsage], None] | None = None,
    ) -> AssistantTurn:
        """Run one turn streamed, reporting its output as it is written.

        Streamed so the reader sees the answer while the model writes it, and
        so a long emission is bounded by the gaps between chunks rather than
        by one whole-response read. The chunks fold back into the completion a
        non-streamed request returns, so the turn parses as ``complete``'s does.
        """
        self._require_client()
        kwargs = {
            **self._request_kwargs(
                system_prompt=system_prompt,
                messages=messages,
                rendered_tools=rendered_tools,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        return self._retrying_empty(
            lambda: self._stream_turn(kwargs, on_event, on_usage),
            before_retry,
            on_event,
        )

    # -- private helpers --------------------------------------------------

    def _require_client(self) -> None:
        if self._client is None:
            raise ProviderError(
                "OPENROUTER_API_KEY is not configured; cannot call OpenRouter."
            )

    def _retrying_empty(
        self,
        request: Callable[[], AssistantTurn],
        before_retry: Callable[[], None] | None,
        on_event: Callable[[ProviderStreamEvent], None] | None = None,
    ) -> AssistantTurn:
        """Run ``request``, repeating it once after a transient empty response."""
        for attempt in range(1 + _EMPTY_RESPONSE_RETRIES):
            try:
                return request()
            except _EmptyResponseError as e:
                # The SDK does not retry a 200, so a response that arrived
                # empty for a transient reason gets its repeat here or not at
                # all. A permanent one is reported without spending again.
                if not e.retryable or attempt == _EMPTY_RESPONSE_RETRIES:
                    raise
                logger.warning(
                    "openrouter: retrying after an empty response (model=%s)",
                    self.model_id,
                )
                if before_retry is not None:
                    before_retry()
                if on_event is not None:
                    # A stream that failed partway may have shown part of an
                    # answer the retry replaces.
                    on_event(StreamReset())
        raise AssertionError("unreachable")  # pragma: no cover

    def _request_kwargs(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int | None,
        temperature: float,
    ) -> dict:
        """The Chat Completions arguments for one turn."""
        capabilities = model_capabilities("openrouter", self.model_id)
        if capabilities.max_output_tokens is None:
            # No guessed ceiling: too high is a 400, too low truncates a turn
            # mid-emission. A model is reviewed before it is served.
            raise ProviderError(
                f"model {self.model_id!r} has no reviewed output ceiling; add "
                "it to model_capabilities before serving it.",
                retryable=False,
            )
        budget = MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens
        kwargs: dict = {
            "model": self.model_id,
            "messages": self._render_messages(system_prompt, messages),
            "max_tokens": min(budget, capabilities.max_output_tokens),
        }
        # OpenRouter forwards params to the upstream provider verbatim, and
        # models that reject sampling params 400 on ``temperature``.
        if capabilities.temperature:
            kwargs["temperature"] = temperature
        if rendered_tools:
            if self.model_id in _GPT6_CHAT_TOOLS_MODELS and self.effort != "none":
                raise ProviderError(
                    "GPT-6 function calling through Chat Completions requires "
                    "reasoning effort 'none'",
                    retryable=False,
                )
            kwargs["tools"] = rendered_tools
        reasoning = self._reasoning()
        if reasoning:
            # ``reasoning`` is an OpenRouter extension rather than an OpenAI
            # Chat Completions argument, so the OpenAI client forwards it via
            # ``extra_body``.
            kwargs["extra_body"] = {"reasoning": reasoning}
        return kwargs

    def _request_turn(
        self, kwargs: dict, on_usage: Callable[[TurnUsage], None] | None
    ) -> AssistantTurn:
        """Send one Chat Completions request and parse its turn."""
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            return self._failed_request(e)
        return self._finished_turn(response, started, on_usage)

    def _stream_turn(
        self,
        kwargs: dict,
        on_event: Callable[[ProviderStreamEvent], None] | None,
        on_usage: Callable[[TurnUsage], None] | None,
    ) -> AssistantTurn:
        """Stream one Chat Completions request and parse its turn."""
        started = time.perf_counter()
        try:
            stream = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            return self._failed_request(e)
        streamed = _StreamedCompletion(on_event)
        try:
            for chunk in stream:
                streamed.add(chunk)
        except Exception as e:
            body = _stream_error_body(e)
            if body is not None:
                return self._no_message_turn({"error": body})
            logger.exception("OpenRouter stream failed")
            raise ProviderError(
                f"OpenRouter stream failed: {e}",
                # A connection dropped mid-emission is as transient as one
                # that failed to open.
                retryable=_is_retryable_error(e) or isinstance(e, httpx.TransportError),
            ) from e
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        response = streamed.completion()
        if not streamed.finished:
            # A connection closed cleanly before the last chunk leaves the SDK
            # nothing to raise. What arrived is a fragment -- possibly a tool
            # call with half its arguments -- so it is never parsed as a turn.
            self._report_usage(response, on_usage)
            logger.warning(
                "openrouter: stream ended before a finish reason (model=%s)",
                self.model_id,
            )
            raise _EmptyResponseError(
                "OpenRouter stream ended before the turn finished", retryable=True
            )
        return self._finished_turn(response, started, on_usage)

    def _failed_request(self, error: Exception) -> AssistantTurn:
        """A refusal turn for a refused request; any other failure raises."""
        refusal = _refusal_error(error)
        if refusal is not None:
            # The same outcome as a refusal the model writes, so it is
            # reported the same way.
            logger.warning(
                "openrouter: request refused (model=%s, error=%r)",
                self.model_id,
                refusal,
            )
            return AssistantTurn(
                text_blocks=[],
                tool_calls=[],
                stop_reason=StopReason.CONTENT_FILTERED,
                stop_details=refusal,
            )
        logger.exception("OpenRouter complete failed")
        raise ProviderError(
            f"OpenRouter complete failed: {error}",
            retryable=_is_retryable_error(error),
        ) from error

    def _finished_turn(
        self,
        response: Any,
        started: float,
        on_usage: Callable[[TurnUsage], None] | None,
    ) -> AssistantTurn:
        """Report a completed response's usage, then parse its turn."""
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._report_usage(response, on_usage)
        return self._parse_turn(response, latency_ms=latency_ms)

    def _report_usage(
        self, response: Any, on_usage: Callable[[TurnUsage], None] | None
    ) -> None:
        self._log_usage(response)
        usage = self._parse_usage(response)
        if usage is not None and on_usage is not None:
            on_usage(usage)

    def _reasoning(self) -> dict:
        """OpenRouter's ``reasoning`` option for this provider's settings."""
        reasoning: dict = {}
        if self.thinking is not None:
            reasoning["enabled"] = self.thinking == "adaptive"
        if self.effort and self.thinking != "disabled":
            reasoning["effort"] = self.effort
        return reasoning

    def _render_messages(
        self, system_prompt: str, messages: list[Message]
    ) -> list[dict]:
        rendered: list[dict] = [{"role": "system", "content": system_prompt}]
        images = RequestImages(
            messages,
            loader=self.image_loader,
            vision=model_capabilities("openrouter", self.model_id).vision,
            max_image_bytes=MAX_IMAGE_BYTES,
            max_request_bytes=MAX_REQUEST_IMAGE_BYTES,
        )
        for message in messages:
            if message.role == "assistant":
                rendered.append(self._render_assistant(message))
            else:
                rendered.extend(self._render_user(message, images))
        return rendered

    def _render_user(self, message: Message, images: RequestImages) -> list[dict]:
        # User-side turns: each tool result becomes its own ``tool`` message
        # keyed by ``tool_call_id`` (the id-correlation invariant), emitted
        # before any plain text so they directly follow the assistant
        # message that issued the calls, as the wire format requires.
        results = sum(isinstance(block, ToolResultBlock) for block in message.content)
        tool_messages: list[dict] = []
        parts: list[dict] = []
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                # No error flag on tool messages in this wire format; the
                # error payload inside ``content`` is what the model sees.
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.tool_use_id,
                        "content": json.dumps(block.content),
                    }
                )
                position = f"{len(tool_messages)} of {results}"
                parts.extend(self._tool_image_parts(block, images, position))
            elif isinstance(block, TextBlock):
                parts.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageBlock):
                parts.extend(self._image_parts(block, images))
            else:
                raise TypeError(f"unrenderable user block: {block!r}")
        if not parts:
            return tool_messages
        content: str | list[dict] = parts
        if all(part["type"] == "text" for part in parts):
            # Text-only turns stay a plain string, as before images existed.
            content = "".join(part["text"] for part in parts)
        return [*tool_messages, {"role": "user", "content": content}]

    def _tool_image_parts(
        self, block: ToolResultBlock, images: RequestImages, position: str
    ) -> list[dict]:
        # Upstreams differ on images in tool messages, so a result's images
        # follow in the user message instead.
        if not block.images:
            return []
        note = _TOOL_IMAGES_NOTE.format(position=position, id=block.tool_use_id)
        parts = [{"type": "text", "text": note}]
        for image in block.images:
            parts.extend(self._image_parts(image, images))
        return parts

    def _image_parts(self, block: ImageBlock, images: RequestImages) -> list[dict]:
        """The image after its label, or its placeholder as text."""
        data = images.load(block)
        if data is None:
            return [{"type": "text", "text": f"{image_placeholder(block)}\n"}]
        encoded = base64.b64encode(data).decode("ascii")
        image = {
            "type": "image_url",
            "image_url": {"url": f"data:{block.media_type};base64,{encoded}"},
        }
        if block.label:
            return [{"type": "text", "text": block.label}, image]
        return [image]

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

    def _no_message_turn(self, response: Any) -> AssistantTurn:
        """Account for a 200 that carries no usable choice.

        OpenRouter passes some upstream failures through as a 200 whose body
        holds an ``error`` object in place of ``choices``. The SDK raises
        nothing for one, so that body is the only account of what went wrong
        and is logged and carried into the failure rather than dropped.
        """
        body = _plain_dict(response)
        error = _body_error(body)
        if _is_refusal(error.get("metadata")):
            # A refusal reported in the body rather than as a 403: the same
            # outcome, so it is reported the same way and the router can send
            # the turn to the fallback model.
            logger.warning(
                "openrouter: request refused in body (model=%s, error=%r)",
                self.model_id,
                error,
            )
            return AssistantTurn(
                text_blocks=[],
                tool_calls=[],
                stop_reason=StopReason.CONTENT_FILTERED,
                stop_details=error,
            )
        logger.warning(
            "openrouter: response carried no message (model=%s, body=%.2000r)",
            self.model_id,
            body,
        )
        raise _EmptyResponseError(
            "Invalid OpenRouter response: missing message "
            f"({_body_error_summary(error)})",
            retryable=_body_error_retryable(error),
        )

    def _parse_turn(
        self, response: Any, *, latency_ms: int | None = None
    ) -> AssistantTurn:
        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        if message is None:
            return self._no_message_turn(response)

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
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        cache_read_tokens = self._cache_detail(usage, "cached_tokens")
        cache_write_tokens = self._cache_detail(usage, "cache_write_tokens")
        uncached_input_tokens = (
            max(
                0,
                prompt_tokens - (cache_read_tokens or 0) - (cache_write_tokens or 0),
            )
            if prompt_tokens is not None
            else None
        )
        return TurnUsage(
            input_tokens=uncached_input_tokens,
            output_tokens=getattr(usage, "completion_tokens", None),
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            provider_cost_microusd=self._provider_cost_microusd(usage),
        )

    @staticmethod
    def _provider_cost_microusd(usage: Any) -> int | None:
        """Normalize OpenRouter's authoritative USD charge to integer micro-USD."""
        raw_cost = getattr(usage, "cost", None)
        if raw_cost is None:
            return None
        try:
            cost = Decimal(str(raw_cost))
        except InvalidOperation, TypeError, ValueError:
            return None
        if not cost.is_finite() or cost < 0:
            return None
        return int(
            (cost * Decimal(1_000_000)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )

    @staticmethod
    def _cached_tokens(usage: Any) -> int | None:
        return OpenRouterProvider._cache_detail(usage, "cached_tokens")

    @staticmethod
    def _cache_detail(usage: Any, name: str) -> int | None:
        details = getattr(usage, "prompt_tokens_details", None)
        if details is None:
            return None
        return getattr(details, name, None)
