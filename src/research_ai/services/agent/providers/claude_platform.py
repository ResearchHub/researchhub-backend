"""Claude Platform on AWS adapter (Anthropic Messages API).

Claude Platform on AWS (https://aws.amazon.com/claude-platform/) is Anthropic's
own Claude Developer Platform reached through AWS: SigV4 request signing, IAM
access control, and AWS Marketplace billing, with same-day feature parity with
the first-party API.

It is **not** Amazon Bedrock, and the two coexist: Bedrock is AWS-operated,
speaks the Converse wire format, lags first-party on features, and takes
``anthropic.``-prefixed model ids. Here the wire format is the Anthropic
Messages API and model ids are the bare first-party strings (``claude-opus-5``)
-- prefixing one would 404. That parity is the reason this adapter exists: the
Opus 5 knobs the proposal-drafting loop wants (adaptive thinking, the effort
ladder) are first-party features.

Auth needs no new secret material: ``AnthropicAWS`` resolves AWS credentials
through the standard chain (env vars, shared profile, assumed role / instance
metadata) exactly as boto3 does, so a deployment only needs the IAM permissions
plus its Claude workspace id (``ANTHROPIC_AWS_WORKSPACE_ID``).
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from anthropic import AnthropicAWS
from django.conf import settings

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.model_capabilities import model_capabilities
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Block,
    Message,
    ProviderStreamEvent,
    ServerToolBlock,
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

logger = logging.getLogger(__name__)

# Default generator model. Bare first-party id -- Claude Platform is
# Anthropic-operated, so it takes no provider prefix and no date suffix.
# Callers that want a different model pass ``model_id``.
MODEL_ID = "claude-opus-5"

# claude-opus-5's output ceiling; what ``max_tokens=None`` resolves to. On
# Opus 5 the budget covers thinking + text together, so an artificially low
# ceiling truncates tool calls mid-emission. Review alongside MODEL_ID.
MAX_OUTPUT_TOKENS = 128_000

# How much the model may deliberate and spend per turn: low | medium | high |
# xhigh | max. ``low`` keeps routine agent workflows economical; higher levels
# trade more tokens for depth. "" omits the parameter entirely (models older
# than 4.5 reject it).
EFFORT = "low"

# Adaptive thinking lets the model choose its own reasoning depth per turn; it
# is the only supported on-mode from Opus 4.6 onward and is already the default
# on Opus 5. Sent explicitly so the loop behaves the same if the model changes.
# "" omits it; "disabled" turns thinking off (Opus 5 accepts that only at
# effort ``high`` or below).
THINKING = "adaptive"

# Readable reasoning must be asked for: from Opus 4.7 on ``display`` defaults
# to "omitted", which returns thinking blocks whose text is empty. "summarized"
# returns a readable summary instead; billing is identical either way. Only
# the adaptive config carries the field.
THINKING_DISPLAY = "summarized"

# Prompt caching is the dominant cost lever for this uncached, ever-growing tool
# loop: the tools+system prefix is byte-identical every turn and the conversation
# only grows by appending, so cache breakpoints turn full-price re-reads into
# ~0.1x cache reads.
PROMPT_CACHING = True

# The turn is streamed, so this applies per phase (connect, and the gap
# between streamed chunks), not to the whole turn -- a healthy long emission
# can exceed it; only a stalled connection trips it. Retries absorb transient
# throttling so one 429 does not kill a long run.
TIMEOUT_SECONDS = 600.0
MAX_RETRIES = 8

# Anthropic's own web search, run server-side inside the turn: the model issues
# a query, the API executes it and injects the results, and generation continues
# -- no client-side round trip and no separate search vendor. Agents opt into
# this capability explicitly; proposal drafting does so instead of registering
# its client-side Brave implementation, while unrelated agents get no search
# tool. Bedrock, which does not offer it, keeps the local implementation.
# ``max_uses`` is the per-turn ceiling the API enforces on the model's behalf.
WEB_SEARCH = True
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"
WEB_SEARCH_TOOL_NAME = "web_search"
WEB_SEARCH_MAX_USES = 6


# Messages API ``stop_reason`` -> neutral ``StopReason``. ``refusal`` is a
# successful HTTP 200 whose content is empty or partial (Opus 5 ships elevated
# safety classifiers), so it maps onto the same "the turn did not complete"
# branch as a content filter rather than looking like a normal end_turn.
_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "model_context_window_exceeded": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "refusal": StopReason.CONTENT_FILTERED,
    # Not a failure: the API ran its per-turn cap of server-side tool calls and
    # handed the turn back mid-flight to be continued.
    "pause_turn": StopReason.PAUSE_TURN,
}

_THINKING_BLOCK_TYPES = ("thinking", "redacted_thinking")

# Provider-managed blocks from the SDK's response union. The loop never
# dispatches these; it replays them verbatim where they sat. Code execution
# results may accompany web search and contain encrypted output, so they are
# replay state even when the caller declared only the web-search tool.
_SERVER_TOOL_BLOCK_TYPES = (
    "server_tool_use",
    "web_search_tool_result",
    "web_fetch_tool_result",
    "code_execution_tool_result",
    "bash_code_execution_tool_result",
    "text_editor_code_execution_tool_result",
    "tool_search_tool_result",
    "container_upload",
)

# Block types a prompt-cache breakpoint may be attached to. Only user-authored
# blocks are eligible: assistant response blocks can carry signed or encrypted
# replay state and must be sent back exactly as received. The tools+system
# breakpoint is unaffected, and the prefix cached on the previous turn is still
# read.
_CACHEABLE_BLOCK_TYPES = ("text", "tool_result")

_PROVIDER_STATE_KEY = "anthropic"


def _build_client() -> AnthropicAWS | None:
    """Build the SigV4 client, or None when the platform is unconfigured.

    Returning None (rather than raising) keeps construction free of side
    effects: the registry and the judge roster build providers just to report
    which model is configured, and only an actual ``complete`` needs creds.
    The two values are checked here rather than left to the SDK because it
    raises on a missing one, which would move the failure into a constructor.
    """
    workspace_id = settings.ANTHROPIC_AWS_WORKSPACE_ID
    region = settings.AWS_REGION_NAME
    if not (workspace_id and region):
        return None
    return AnthropicAWS(
        aws_region=region,
        workspace_id=workspace_id,
        timeout=TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )


def _block_payload(block: Any) -> dict:
    """Best-effort plain-dict copy of an SDK content block."""
    dump = getattr(block, "model_dump", None)
    if callable(dump):
        payload = dump(mode="json", exclude_none=True)
        return payload if isinstance(payload, dict) else {}
    return dict(block) if isinstance(block, dict) else {}


def _block_type(block: Any) -> str | None:
    """Read a content-block discriminator from an SDK model or raw dict."""
    block_type = getattr(block, "type", None)
    if block_type is None and isinstance(block, dict):
        block_type = block.get("type")
    return block_type if isinstance(block_type, str) else None


@dataclass(frozen=True)
class _ContinuationDiagnostics:
    """What an assistant turn left open, as far as continuation is concerned.

    ``programmatic_calls`` counts client tool calls tagged with a
    code-execution ``caller``; ``pending_server_spans`` counts server-tool
    requests with no matching result in the turn; ``open_code_execution_spans``
    is the subset of those that belong to code execution.
    """

    programmatic_calls: int
    pending_server_spans: int
    open_code_execution_spans: int

    @property
    def needs_container(self) -> bool:
        """Whether continuing past this turn requires a container id.

        Either signal alone is sufficient: the API demands a container when a
        turn left code execution open, whether that shows up as caller-tagged
        client tool calls or as an unresolved code execution span -- the
        observed dynamic-filtering shape carries no ``caller`` metadata, so
        the caller tag alone undercounts.
        """
        return bool(self.programmatic_calls or self.open_code_execution_spans)


def _continuation_diagnostics(blocks: list[Any]) -> _ContinuationDiagnostics:
    """Measure what a turn's blocks leave open for continuation.

    Operates on rendered request dictionaries and SDK response blocks so the
    request and response log lines measure the exact wire shapes on each side.
    """
    programmatic_calls = 0
    server_tool_uses: dict[str, str] = {}
    server_tool_results: set[str] = set()

    for block in blocks:
        payload = _block_payload(block)
        block_type = payload.get("type")
        if block_type == "tool_use":
            caller = payload.get("caller")
            if isinstance(caller, dict) and str(caller.get("type", "")).startswith(
                "code_execution_"
            ):
                programmatic_calls += 1
        elif block_type == "server_tool_use":
            tool_use_id = payload.get("id")
            if isinstance(tool_use_id, str):
                server_tool_uses[tool_use_id] = str(payload.get("name", ""))
        elif block_type in _SERVER_TOOL_BLOCK_TYPES:
            tool_use_id = payload.get("tool_use_id")
            if isinstance(tool_use_id, str):
                server_tool_results.add(tool_use_id)

    unresolved = {
        tool_use_id: name
        for tool_use_id, name in server_tool_uses.items()
        if tool_use_id not in server_tool_results
    }
    return _ContinuationDiagnostics(
        programmatic_calls=programmatic_calls,
        pending_server_spans=len(unresolved),
        open_code_execution_spans=sum(
            1 for name in unresolved.values() if "code_execution" in name
        ),
    )


def _latest_assistant_content(rendered_messages: list[dict]) -> list[dict]:
    """Return the assistant content immediately preceding this request."""
    for message in reversed(rendered_messages):
        if message.get("role") == "assistant":
            content = message.get("content")
            return content if isinstance(content, list) else []
    return []


def _message_container(message: Message) -> dict | None:
    """Read the Claude container metadata recorded on one assistant message."""
    anthropic_state = message.provider_state.get(_PROVIDER_STATE_KEY)
    if not isinstance(anthropic_state, dict):
        return None
    container = anthropic_state.get("container")
    return container if isinstance(container, dict) else None


def _container_id(messages: list[Message]) -> str | None:
    """Return this conversation's code-execution container, if one was created.

    The container is conversation state, not per-turn state: Anthropic returns
    the container object once, on the turn that creates it, and does not echo it
    back on later turns even when the request carried it. So the most recent
    identifier anywhere in the history is the one this conversation is using.

    Liveness is deliberately not guessed at. Two signals look like they report
    it, and neither does:

    - The shape of a turn's tool calls. With web-search dynamic filtering the
      API runs code execution inside the turn, and the model mixes ordinary tool
      calls with ones its filtering code issues. An ordinary turn does not mean
      the container died, and a later code-generated call still needs the
      container an earlier turn established. A ``pause_turn`` continuation may
      carry no client tool calls at all and still resume work in it.
    - The recorded ``expires_at``. Anthropic documents it as a short rolling
      value that deliberately does not report the real limit: a container lives
      30 days from creation, and a few minutes' inactivity only checkpoints it --
      sending the identifier inside that window restores it. A timestamp in the
      past therefore routinely names a container that is still usable.

    Acting on either drops an identifier the next request needs, and a request
    that owes results to paused code is rejected outright without it. Anthropic
    is the only party that knows whether a container is still good, so the
    identifier is kept for the conversation and the API decides -- as the SDK's
    own tool runner does (``anthropic/lib/tools/_beta_runner.py``), which
    likewise never retires one. The documented recovery from a genuinely expired
    container is to resend without the ``container`` parameter, which is a
    response to the API's error rather than something to predict here.
    """
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        container = _message_container(message)
        if container is None:
            continue
        container_id = container.get("id")
        if isinstance(container_id, str):
            return container_id
    return None


class ClaudePlatformProvider(LLMProvider):
    """Adapts the neutral agent types to the Anthropic Messages API on AWS."""

    def __init__(
        self,
        *,
        client: Any = None,
        model_id: str | None = None,
        web_search: bool = False,
        effort: str | None = None,
        thinking: str | None = None,
    ):
        self.model_id = model_id or MODEL_ID
        self._client = client if client is not None else _build_client()
        self.prompt_caching = PROMPT_CACHING
        self.effort = EFFORT if effort is None else effort
        self.thinking = THINKING if thinking is None else thinking
        self.web_search = web_search and WEB_SEARCH
        self.web_search_max_uses = WEB_SEARCH_MAX_USES

    # -- public surface ---------------------------------------------------

    @property
    def native_tool_names(self) -> frozenset[str]:
        """``web_search`` when server-side search is on; nothing otherwise."""
        return frozenset({WEB_SEARCH_TOOL_NAME} if self.web_search else ())

    def render_tools(self, tools: list[Tool]) -> list[dict]:
        """Render tools to the Messages API ``tools`` list.

        Server-side tools are appended after the caller's, in a fixed order:
        tools render at the head of the prompt, so the list has to be
        byte-identical every turn for the cached prefix to hold.
        """
        rendered = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
        if self.web_search:
            rendered.append(
                {
                    "type": WEB_SEARCH_TOOL_TYPE,
                    "name": WEB_SEARCH_TOOL_NAME,
                    "max_uses": self.web_search_max_uses,
                }
            )
        return rendered

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
        return self.complete_with_events(
            system_prompt=system_prompt,
            messages=messages,
            rendered_tools=rendered_tools,
            max_tokens=max_tokens,
            temperature=temperature,
            before_retry=before_retry,
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
    ) -> AssistantTurn:
        if self._client is None:
            raise ProviderError(
                "Claude Platform on AWS is not configured "
                "(needs ANTHROPIC_AWS_WORKSPACE_ID and AWS_REGION_NAME); "
                "cannot complete a turn."
            )

        kwargs = self._request_kwargs(
            system_prompt=system_prompt,
            messages=messages,
            rendered_tools=rendered_tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        diagnostics = _continuation_diagnostics(
            _latest_assistant_content(kwargs["messages"]),
        )
        logger.info(
            "claude platform request continuation: "
            "request_container_present=%s "
            "pending_programmatic_tool_calls=%s "
            "pending_server_tool_spans=%s "
            "open_code_execution_spans=%s",
            "container" in kwargs,
            diagnostics.programmatic_calls,
            diagnostics.pending_server_spans,
            diagnostics.open_code_execution_spans,
        )
        if diagnostics.needs_container and "container" not in kwargs:
            # The API rejects this request outright ("container_id is required
            # when there are pending tool uses generated by code execution"):
            # the latest assistant turn left code execution open -- either its
            # tool calls carry a code-execution caller, or its code execution
            # span never resolved -- and only the container that code runs in
            # can consume what this request sends back. No id anywhere in the
            # history means the API never disclosed one (observed on
            # dynamic-filtering turns) or the conversation predates container
            # persistence -- either way this conversation cannot resume past
            # that turn, and retrying will fail identically. Failing here
            # names the actual cause instead of spending an API call to
            # receive the same verdict as a bare 400.
            raise ProviderError(
                "Cannot resume this conversation: its latest assistant turn "
                f"left code execution open ({diagnostics.programmatic_calls} "
                "programmatic tool call(s), "
                f"{diagnostics.open_code_execution_spans} unresolved code "
                "execution span(s)), but no container id was ever recorded "
                "for the conversation. Only a fresh conversation/context can "
                "recover."
            )

        started = time.perf_counter()
        responses = []
        for attempt in range(2):
            try:
                # Streamed so a turn's wall clock is bounded by chunk gaps,
                # not the whole emission -- a full-budget turn legitimately
                # outlives any sane whole-request timeout.
                response = self._stream_turn(kwargs, on_event=on_event)
            except Exception as e:
                logger.exception("Claude Platform complete failed")
                raise ProviderError(f"Claude Platform complete failed: {e}") from e
            responses.append(response)
            self._log_usage(response)
            self._log_continuation_state(response)
            if not self._response_missing_required_container(
                response, request_container_id=kwargs.get("container")
            ):
                break
            if attempt == 0:
                if before_retry is not None:
                    before_retry()
                if on_event is not None:
                    # The first response is intentionally discarded. Replace
                    # its transient preview before streaming the retry so the
                    # two attempts cannot be presented as one answer.
                    on_event(StreamReset())
                # Do not persist a response the next request cannot replay.
                # Repeating the identical stateless request gives Platform one
                # chance to finish the server-side loop or disclose its
                # container, without re-running any client-side tools.
                logger.warning(
                    "claude platform: retrying response that left code "
                    "execution open without a container"
                )
        else:
            raise ProviderError(
                "Claude Platform repeatedly returned an unfinished code "
                "execution span without the container id required to resume "
                "it; the unreplayable response was not added to the "
                "conversation."
            )
        latency_ms = int((time.perf_counter() - started) * 1000)

        turn = self._parse_turn(response, latency_ms=latency_ms)
        if len(responses) > 1:
            turn = replace(turn, usage=self._combined_usage(responses))
        return turn

    # -- private helpers --------------------------------------------------

    def _stream_turn(self, kwargs: dict, *, on_event=None) -> Any:
        """Stream one turn, restoring the container the SDK accumulator drops.

        Anthropic discloses the code-execution container on ``message_delta``,
        and the accumulator behind ``get_final_message`` copies only stop and
        usage fields off that event -- so the id every later request needs to
        resume the container reaches this process only through the events.
        """
        container = None
        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                self._report_stream_event(event, on_event)
                # The SDK declares it on the event's ``delta``; an id the API
                # sends elsewhere lands on the event itself as a model extra.
                delta = getattr(event, "delta", None)
                disclosed = getattr(delta, "container", None) or getattr(
                    event, "container", None
                )
                if disclosed is not None:
                    container = disclosed
            response = stream.get_final_message()
        if container is not None:
            response.container = container
        return response

    def _request_kwargs(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int | None,
        temperature: float,
    ) -> dict:
        """Build optional and required Messages API request fields."""
        system: dict = {"type": "text", "text": system_prompt}
        if self.prompt_caching:
            # Render order is tools -> system -> messages, so one breakpoint on
            # the system block caches the whole tools+system prefix -- the
            # bytes that repeat unchanged on every turn.
            system["cache_control"] = {"type": "ephemeral"}
        kwargs: dict = {
            "model": self.model_id,
            "max_tokens": MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens,
            "system": [system],
            "messages": self._render_messages(messages, cache_last=self.prompt_caching),
        }
        if rendered_tools:
            kwargs["tools"] = rendered_tools
        container_id = _container_id(messages)
        if container_id:
            # Required when code execution paused on a tool call, and useful
            # for ordinary container reuse. The identifier is response-level
            # state, separate from the content blocks replayed above.
            kwargs["container"] = container_id
            logger.info("claude platform: reusing code execution container")
        capabilities = model_capabilities("claude_platform", self.model_id)
        thinking_mode = self.thinking if self.thinking in capabilities.thinking else ""
        if thinking_mode:
            thinking: dict = {"type": thinking_mode}
            if thinking_mode == "adaptive" and THINKING_DISPLAY:
                thinking["display"] = THINKING_DISPLAY
            kwargs["thinking"] = thinking
        if self.effort and self.effort in capabilities.effort:
            kwargs["output_config"] = {"effort": self.effort}
        # Thinking pins temperature to its default, so forwarding the loop's
        # value is at best a no-op and at worst a 400 -- omit it whenever the
        # model or the thinking config rules it out.
        if thinking_mode != "adaptive" and capabilities.temperature:
            kwargs["temperature"] = temperature
        return kwargs

    # Content block types whose opening marks the model composing a tool call:
    # our own tools and the ones Anthropic runs server-side (web search, code
    # execution). Their arguments then arrive as ``input_json_delta`` chunks.
    _TOOL_USE_BLOCK_TYPES = frozenset({"tool_use", "server_tool_use"})

    @classmethod
    def _report_stream_event(cls, event: Any, on_event) -> None:
        """Translate SDK events into the provider-neutral streaming surface."""
        if on_event is None:
            return
        stream_event = cls._stream_event(event)
        if stream_event is not None:
            on_event(stream_event)

    @classmethod
    def _stream_event(cls, event: Any) -> ProviderStreamEvent | None:
        """Return the provider-neutral event represented by one SDK event."""
        index = getattr(event, "index", None)
        if not isinstance(index, int):
            return None
        event_type = getattr(event, "type", None)
        if event_type == "content_block_start":
            return cls._tool_use_stream_start(event, index)
        if event_type == "content_block_delta":
            return cls._stream_delta(event, index)
        return None

    @classmethod
    def _tool_use_stream_start(
        cls, event: Any, index: int
    ) -> ToolUseStreamStart | None:
        block = getattr(event, "content_block", None)
        if getattr(block, "type", None) not in cls._TOOL_USE_BLOCK_TYPES:
            return None
        name = getattr(block, "name", None)
        if not isinstance(name, str) or not name:
            return None
        return ToolUseStreamStart(block_index=index, name=name)

    @staticmethod
    def _stream_delta(event: Any, index: int) -> ProviderStreamEvent | None:
        delta = getattr(event, "delta", None)
        if delta is None:
            return None
        delta_type = getattr(delta, "type", None)
        if delta_type == "text_delta":
            text = getattr(delta, "text", None)
            if isinstance(text, str) and text:
                return TextStreamDelta(block_index=index, text=text)
        if delta_type == "thinking_delta":
            thinking = getattr(delta, "thinking", None)
            if isinstance(thinking, str) and thinking:
                return ThinkingStreamDelta(block_index=index, text=thinking)
        if delta_type == "input_json_delta":
            partial_json = getattr(delta, "partial_json", None)
            if isinstance(partial_json, str) and partial_json:
                return ToolInputStreamDelta(
                    block_index=index, partial_json=partial_json
                )
        return None

    def _render_messages(
        self, messages: list[Message], *, cache_last: bool = False
    ) -> list[dict]:
        rendered = [
            {"role": m.role, "content": [self._render_block(b) for b in m.content]}
            for m in messages
        ]
        if (
            cache_last
            and rendered
            and rendered[-1]["role"] == "user"
            and rendered[-1]["content"]
        ):
            # Cache the conversation prefix through the latest turn; the next
            # turn re-sends these same messages as a prefix and reads the cache.
            # Usually the loop completes from a user turn and this lands on text
            # or a tool result -- but a paused turn is resumed with the assistant
            # turn last, and its final block may be one that must not be edited.
            last = rendered[-1]["content"][-1]
            if last.get("type") in _CACHEABLE_BLOCK_TYPES:
                last["cache_control"] = {"type": "ephemeral"}
        return rendered

    def _render_block(self, block: Any) -> dict:
        if isinstance(block, TextBlock):
            if block.data is not None:
                # Citation-bearing assistant text contains encrypted replay
                # state. Keep the provider block whole rather than rebuilding
                # it from the visible text alone.
                return dict(block.data)
            return {"type": "text", "text": block.text}
        if isinstance(block, ThinkingBlock):
            # Replayed byte-for-byte: these blocks are signed, and an edited or
            # missing one fails validation on the next turn.
            return dict(block.data)
        if isinstance(block, ServerToolBlock):
            # Same contract, for the tools the API ran itself: replay the
            # request and its injected result unedited and still paired.
            return dict(block.data)
        if isinstance(block, ToolUseBlock):
            if block.data is not None:
                # Programmatic tool calls include a ``caller`` that ties the
                # call to pending code in the container. Replay the complete
                # block rather than reconstructing only the common fields.
                return dict(block.data)
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
        if isinstance(block, ToolResultBlock):
            # Unlike Converse, this wire format carries tool results as text.
            # Toolset.dispatch validates the normal path; keep this adapter
            # strict as well for directly constructed messages.
            try:
                content = json.dumps(
                    block.content,
                    allow_nan=False,
                    ensure_ascii=False,
                )
            except (TypeError, ValueError, RecursionError) as exc:
                raise ProviderError(
                    f"Tool result {block.tool_use_id!r} is not valid JSON"
                ) from exc
            tool_result: dict = {
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": content,
            }
            if block.is_error:
                tool_result["is_error"] = True
            return tool_result
        raise TypeError(f"unrenderable block: {block!r}")

    def _log_usage(self, response: Any) -> None:
        """Log token usage so cache hits are observable.

        After the first turn, ``cache_read`` should dominate ``input`` if
        caching is landing; a persistent ``cache_read=0`` means a silent
        invalidator.
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        logger.info(
            "claude platform usage: input=%s cache_read=%s cache_write=%s "
            "output=%s container_returned=%s",
            getattr(usage, "input_tokens", None),
            getattr(usage, "cache_read_input_tokens", None),
            getattr(usage, "cache_creation_input_tokens", None),
            getattr(usage, "output_tokens", None),
            getattr(response, "container", None) is not None,
        )

    def _log_continuation_state(self, response: Any) -> None:
        """Log response-level state needed to diagnose container continuation."""
        content = getattr(response, "content", None)
        blocks = content if isinstance(content, list) else []
        diagnostics = _continuation_diagnostics(blocks)
        logger.info(
            "claude platform response continuation: "
            "response_container_present=%s "
            "pending_programmatic_tool_calls=%s "
            "pending_server_tool_spans=%s "
            "open_code_execution_spans=%s "
            "stop_reason=%s",
            getattr(response, "container", None) is not None,
            diagnostics.programmatic_calls,
            diagnostics.pending_server_spans,
            diagnostics.open_code_execution_spans,
            getattr(response, "stop_reason", None),
        )
        if diagnostics.needs_container and getattr(response, "container", None) is None:
            # The shape behind the "container_id is required" 400: the turn
            # left code execution open, so its continuation needs the
            # container -- but this response did not disclose one. Unless an
            # earlier turn recorded the id, the conversation is now
            # unresumable, and only the request/response ids can carry that
            # to an upstream report.
            logger.warning(
                "claude platform: turn left code execution open without "
                "returning its container "
                "(programmatic_calls=%s open_code_execution_spans=%s)",
                diagnostics.programmatic_calls,
                diagnostics.open_code_execution_spans,
            )

    @staticmethod
    def _response_missing_required_container(
        response: Any, *, request_container_id: str | None
    ) -> bool:
        content = getattr(response, "content", None)
        blocks = content if isinstance(content, list) else []
        return (
            _continuation_diagnostics(blocks).needs_container
            and request_container_id is None
            and getattr(response, "container", None) is None
        )

    def _combined_usage(self, responses: list[Any]) -> TurnUsage | None:
        usages = [self._parse_usage(response) for response in responses]
        present = [usage for usage in usages if usage is not None]
        if not present:
            return None

        def total(field: str) -> int | None:
            values = [getattr(usage, field) for usage in present]
            reported = [value for value in values if value is not None]
            return sum(reported) if reported else None

        return TurnUsage(
            input_tokens=total("input_tokens"),
            output_tokens=total("output_tokens"),
            cache_read_tokens=total("cache_read_tokens"),
            cache_write_tokens=total("cache_write_tokens"),
        )

    def _parse_turn(self, response: Any, *, latency_ms: int | None = None):
        content = getattr(response, "content", None)
        if content is None:
            raise ProviderError("Invalid Claude Platform response: missing content")

        text_blocks: list[TextBlock] = []
        thinking_blocks: list[ThinkingBlock] = []
        tool_calls: list[ToolUseBlock] = []
        # The turn as sent, in order -- what gets replayed. The grouped lists
        # above are views onto these same blocks for the loop's own use.
        content_blocks: list[Block] = []
        for block in content:
            block_type = _block_type(block)
            parsed: Block
            if block_type == "text":
                parsed = TextBlock(text=block.text, data=_block_payload(block))
                text_blocks.append(parsed)
            elif block_type in _THINKING_BLOCK_TYPES:
                parsed = ThinkingBlock(data=_block_payload(block))
                thinking_blocks.append(parsed)
            elif block_type in _SERVER_TOOL_BLOCK_TYPES:
                parsed = ServerToolBlock(data=_block_payload(block))
            elif block_type == "tool_use":
                parsed = ToolUseBlock(
                    id=block.id,
                    name=block.name,
                    input=dict(getattr(block, "input", None) or {}),
                    data=_block_payload(block),
                )
                tool_calls.append(parsed)
            else:
                # Claude can add response block types independently of this
                # adapter. Preserve a new block opaquely when its complete
                # typed payload is available: dropping or reconstructing it
                # could corrupt signed/encrypted replay state, while rejecting
                # it would turn a provider migration into an outage.
                payload = _block_payload(block)
                if not block_type or payload.get("type") != block_type:
                    raise ProviderError(
                        "Claude Platform content block cannot be replayed safely: "
                        f"{block_type!r}"
                    )
                logger.warning(
                    "claude platform: preserving unrecognized content block %r",
                    block_type,
                )
                parsed = ServerToolBlock(data=payload)
            content_blocks.append(parsed)

        raw_stop_reason = getattr(response, "stop_reason", None)
        stop_reason = _STOP_REASONS.get(raw_stop_reason, StopReason.OTHER)
        stop_details = _block_payload(getattr(response, "stop_details", None)) or None
        if stop_reason is StopReason.OTHER:
            # Worth a line: an unmapped stop reason ends the run as a generic
            # incomplete turn, and only the raw value says why.
            logger.warning(
                "claude platform: unmapped stop_reason %r (stop_details=%r)",
                raw_stop_reason,
                stop_details,
            )
        elif stop_reason is StopReason.CONTENT_FILTERED:
            # A refusal is an HTTP 200 whose content is empty, so nothing
            # downstream can tell which classifier fired -- only this payload
            # names the category, and only here does the raw response survive.
            logger.warning(
                "claude platform: turn refused by safety classifiers "
                "(model=%s, stop_details=%r)",
                self.model_id,
                stop_details,
            )
        container = getattr(response, "container", None)
        container_payload = _block_payload(container)
        provider_state = (
            {_PROVIDER_STATE_KEY: {"container": container_payload}}
            if isinstance(container_payload.get("id"), str)
            else {}
        )
        return AssistantTurn(
            text_blocks=text_blocks,
            thinking_blocks=thinking_blocks,
            tool_calls=tool_calls,
            content_blocks=content_blocks,
            stop_reason=stop_reason,
            raw=_block_payload(response),
            stop_details=stop_details,
            usage=self._parse_usage(response),
            latency_ms=latency_ms,
            provider_state=provider_state,
        )

    def _parse_usage(self, response: Any) -> TurnUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        return TurnUsage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
        )
