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
from typing import Any

from anthropic import AnthropicAWS
from django.conf import settings

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
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
}

_THINKING_BLOCK_TYPES = ("thinking", "redacted_thinking")


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
        return dump(mode="json", exclude_none=True)
    return dict(block) if isinstance(block, dict) else {}


class ClaudePlatformProvider(LLMProvider):
    """Adapts the neutral agent types to the Anthropic Messages API on AWS."""

    def __init__(self, *, client: Any = None, model_id: str | None = None):
        self.model_id = model_id or MODEL_ID
        self._client = client if client is not None else _build_client()
        self.prompt_caching = PROMPT_CACHING
        self.effort = EFFORT
        self.thinking = THINKING

    # -- public surface ---------------------------------------------------

    def render_tools(self, tools: list[Tool]) -> list[dict]:
        """Render tools to the Messages API ``tools`` list."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]

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
        if self.thinking:
            kwargs["thinking"] = {"type": self.thinking}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        # Thinking pins temperature to its default, so forwarding the loop's
        # value is at best a no-op and at worst a 400 -- omit it whenever the
        # model or the thinking config rules it out.
        if not self.thinking and _accepts_sampling_params(self.model_id):
            kwargs["temperature"] = temperature

        started = time.perf_counter()
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as e:
            logger.exception("Claude Platform complete failed")
            raise ProviderError(f"Claude Platform complete failed: {e}") from e
        latency_ms = int((time.perf_counter() - started) * 1000)

        self._log_usage(response)
        return self._parse_turn(response, latency_ms=latency_ms)

    # -- private helpers --------------------------------------------------

    def _render_messages(
        self, messages: list[Message], *, cache_last: bool = False
    ) -> list[dict]:
        rendered = [
            {"role": m.role, "content": [self._render_block(b) for b in m.content]}
            for m in messages
        ]
        if cache_last and rendered and rendered[-1]["content"]:
            # Cache the conversation prefix through the latest turn; the next
            # turn re-sends these same messages as a prefix and reads the cache.
            # The loop only ever completes from a user turn, so the block this
            # lands on is text or a tool result, never a signed reasoning block.
            rendered[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
        return rendered

    def _render_block(self, block: Any) -> dict:
        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text}
        if isinstance(block, ThinkingBlock):
            # Replayed byte-for-byte: these blocks are signed, and an edited or
            # missing one fails validation on the next turn.
            return dict(block.data)
        if isinstance(block, ToolUseBlock):
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
        if isinstance(block, ToolResultBlock):
            # Unlike Converse, this wire format carries tool results as text --
            # ``default=str`` keeps one stray non-JSON value in a tool payload
            # from taking down the whole turn.
            tool_result: dict = {
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": json.dumps(block.content, ensure_ascii=False, default=str),
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
            "claude platform usage: input=%s cache_read=%s cache_write=%s output=%s",
            getattr(usage, "input_tokens", None),
            getattr(usage, "cache_read_input_tokens", None),
            getattr(usage, "cache_creation_input_tokens", None),
            getattr(usage, "output_tokens", None),
        )

    def _parse_turn(self, response: Any, *, latency_ms: int | None = None):
        content = getattr(response, "content", None)
        if content is None:
            raise ProviderError("Invalid Claude Platform response: missing content")

        text_blocks: list[TextBlock] = []
        thinking_blocks: list[ThinkingBlock] = []
        tool_calls: list[ToolUseBlock] = []
        for block in content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_blocks.append(TextBlock(text=block.text))
            elif block_type in _THINKING_BLOCK_TYPES:
                thinking_blocks.append(ThinkingBlock(data=_block_payload(block)))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolUseBlock(
                        id=block.id,
                        name=block.name,
                        input=dict(getattr(block, "input", None) or {}),
                    )
                )

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
        return AssistantTurn(
            text_blocks=text_blocks,
            thinking_blocks=thinking_blocks,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=_block_payload(response),
            usage=self._parse_usage(response),
            latency_ms=latency_ms,
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
