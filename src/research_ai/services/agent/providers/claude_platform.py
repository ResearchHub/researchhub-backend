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
from datetime import UTC, datetime
from typing import Any

from anthropic import AnthropicAWS
from django.conf import settings

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Block,
    Message,
    ServerToolBlock,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnUsage,
)

logger = logging.getLogger(__name__)

# Default generator model. Bare first-party id -- Claude Platform is
# Anthropic-operated, so it takes no provider prefix and no date suffix.
# Callers that want a different model pass ``model_id``.
MODEL_ID = "claude-opus-5"

# How much the model may deliberate and spend per turn: low | medium | high |
# xhigh | max. ``high`` is the API default and the closest match to the prior
# Bedrock behaviour; ``xhigh`` trades tokens for depth on agentic work, and
# medium/low are the cost lever. "" omits the parameter entirely (models older
# than 4.5 reject it).
EFFORT = "high"

# Adaptive thinking lets the model choose its own reasoning depth per turn; it
# is the only supported on-mode from Opus 4.6 onward and is already the default
# on Opus 5. Sent explicitly so the loop behaves the same if the model changes.
# "" omits it; "disabled" turns thinking off (Opus 5 accepts that only at
# effort ``high`` or below).
THINKING = "adaptive"

# Prompt caching is the dominant cost lever for this uncached, ever-growing tool
# loop: the tools+system prefix is byte-identical every turn and the conversation
# only grows by appending, so cache breakpoints turn full-price re-reads into
# ~0.1x cache reads.
PROMPT_CACHING = True

# An agent turn that thinks and writes a full proposal section runs long; an
# explicit timeout also suppresses the SDK's non-streaming duration guard.
# Retries absorb transient throttling so one 429 does not kill a long run.
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

# Models that reject sampling params (temperature/top_p/top_k) with a 400.
# Everything from Opus 4.7 on dropped them; the loop's temperature is simply
# not forwarded for those.
_NO_SAMPLING_PARAMS = (
    "opus-4-7",
    "opus-4-8",
    "opus-5",
    "sonnet-5",
    "fable",
    "mythos",
)

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


def _accepts_sampling_params(model_id: str) -> bool:
    mid = model_id.lower()
    return not any(tag in mid for tag in _NO_SAMPLING_PARAMS)


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


def _continuation_diagnostics(blocks: list[Any]) -> tuple[int, int]:
    """Count programmatic calls and unresolved server-tool spans.

    Operates on rendered request dictionaries and SDK response blocks so the
    request and response log lines measure the exact wire shapes on each side.
    """
    programmatic_calls = 0
    server_tool_uses: set[str] = set()
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
                server_tool_uses.add(tool_use_id)
        elif block_type in _SERVER_TOOL_BLOCK_TYPES:
            tool_use_id = payload.get("tool_use_id")
            if isinstance(tool_use_id, str):
                server_tool_results.add(tool_use_id)

    return programmatic_calls, len(server_tool_uses - server_tool_results)


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


def _container_expired(container: dict, *, now: datetime) -> bool:
    """Whether the container's own expiry has passed.

    An absent or unparseable ``expires_at`` counts as live: the identifier is
    the only way to resume pending execution, so a missing timestamp must not
    be the reason a turn loses it.
    """
    expires_at = container.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry <= now


def _container_id(messages: list[Message]) -> str | None:
    """Return this conversation's live code-execution container, if any.

    The container is conversation state, not per-turn state: Anthropic returns
    the container object once, on the turn that creates it, and does not echo it
    back on later turns even when the request carried it. So the most recent
    identifier anywhere in the history is the live one, and ``expires_at`` --
    which Anthropic supplies alongside it -- is what says when it stopped being
    live.

    Liveness cannot be inferred from the shape of a turn's tool calls. With
    web-search dynamic filtering the API runs code execution inside the turn,
    and the model mixes ordinary tool calls with ones its filtering code issues.
    An ordinary turn therefore does not mean the container died, and a later
    code-generated call still needs the container an earlier turn established.
    """
    now = datetime.now(UTC)
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        container = _message_container(message)
        if container is None:
            continue
        container_id = container.get("id")
        if not isinstance(container_id, str):
            continue
        if _container_expired(container, now=now):
            # Anthropic has reclaimed it. Sending a dead identifier fails the
            # turn outright, where omitting it lets the API provision a fresh
            # container -- so stop at the newest one rather than reaching for an
            # older, even more expired id.
            logger.warning(
                "claude platform: code execution container %s expired", container_id
            )
            return None
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
    ):
        self.model_id = model_id or MODEL_ID
        self._client = client if client is not None else _build_client()
        self.prompt_caching = PROMPT_CACHING
        self.effort = EFFORT
        self.thinking = THINKING
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
        max_tokens: int,
        temperature: float,
    ) -> AssistantTurn:
        if self._client is None:
            raise ProviderError(
                "Claude Platform on AWS is not configured "
                "(needs ANTHROPIC_AWS_WORKSPACE_ID and AWS_REGION_NAME); "
                "cannot complete a turn."
            )

        system: dict = {"type": "text", "text": system_prompt}
        if self.prompt_caching:
            # Render order is tools -> system -> messages, so one breakpoint on
            # the system block caches the whole tools+system prefix -- the
            # bytes that repeat unchanged on every turn.
            system["cache_control"] = {"type": "ephemeral"}
        kwargs: dict = {
            "model": self.model_id,
            "max_tokens": max_tokens,
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
        if self.thinking:
            kwargs["thinking"] = {"type": self.thinking}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        # Thinking pins temperature to its default, so forwarding the loop's
        # value is at best a no-op and at worst a 400 -- omit it whenever the
        # model or the thinking config rules it out.
        if not self.thinking and _accepts_sampling_params(self.model_id):
            kwargs["temperature"] = temperature

        request_programmatic_calls, request_pending_server_spans = (
            _continuation_diagnostics(
                _latest_assistant_content(kwargs["messages"]),
            )
        )
        logger.info(
            "claude platform request continuation: "
            "request_container_present=%s "
            "pending_programmatic_tool_calls=%s "
            "pending_server_tool_spans=%s",
            "container" in kwargs,
            request_programmatic_calls,
            request_pending_server_spans,
        )

        started = time.perf_counter()
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as e:
            logger.exception("Claude Platform complete failed")
            raise ProviderError(f"Claude Platform complete failed: {e}") from e
        latency_ms = int((time.perf_counter() - started) * 1000)

        self._log_usage(response)
        self._log_continuation_state(response)
        return self._parse_turn(response, latency_ms=latency_ms)

    # -- private helpers --------------------------------------------------

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
        programmatic_calls, pending_server_spans = _continuation_diagnostics(blocks)
        logger.info(
            "claude platform response continuation: "
            "response_container_present=%s "
            "pending_programmatic_tool_calls=%s "
            "pending_server_tool_spans=%s "
            "stop_reason=%s",
            getattr(response, "container", None) is not None,
            programmatic_calls,
            pending_server_spans,
            getattr(response, "stop_reason", None),
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
        if stop_reason is StopReason.OTHER:
            # Worth a line: an unmapped stop reason ends the run as a generic
            # incomplete turn, and only the raw value says why.
            logger.warning(
                "claude platform: unmapped stop_reason %r (stop_details=%r)",
                raw_stop_reason,
                getattr(response, "stop_details", None),
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
