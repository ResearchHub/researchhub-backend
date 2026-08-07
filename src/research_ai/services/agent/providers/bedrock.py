"""Bedrock Converse adapter.

Wraps the timeout-configured Converse client from ``utils.aws`` and renders the
neutral agent types to/from the Converse wire format. This is a faithful port of
the proven single-provider tool loop (``BedrockLLMService.run_tool_loop``),
split into the provider-agnostic ``LLMProvider`` shape.
"""

import logging
from typing import Any

from research_ai.services.agent import heartbeat
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
from utils.aws import bedrock_runtime_client

logger = logging.getLogger(__name__)

# Default generator model. Bedrock requires the cross-region inference profile
# (the ``us.`` prefix); the bare ``anthropic.claude-opus-5`` is provisioned-
# throughput only. Callers that want a different model pass ``model_id``.
MODEL_ID = "us.anthropic.claude-opus-5"

# Prompt caching is the dominant cost lever for this uncached, ever-growing tool
# loop: the tools+system prefix is byte-identical every turn and the conversation
# only grows by appending, so cache points turn full-price re-reads into ~0.1x
# cache reads. On for Claude-on-Bedrock; a caller running a model without cache
# support turns it off on the instance.
PROMPT_CACHING = True

# Opus 4.7+, Sonnet 5, and Fable reject sampling params (temperature/top_p/
# top_k) with a 400 ("`temperature` is deprecated for this model"). Match by
# substring so the provider omits them for those models.
_NO_SAMPLING_PARAMS = (
    "opus-4-7",
    "opus-4-8",
    "opus-5",
    "sonnet-5",
    "fable",
    "mythos",
)


def _accepts_sampling_params(model_id: str) -> bool:
    mid = model_id.lower()
    return not any(tag in mid for tag in _NO_SAMPLING_PARAMS)


# Bedrock Converse ``stopReason`` -> neutral ``StopReason``. Anything absent
# here (``malformed_model_output``, ``malformed_tool_use``) falls through to
# OTHER, which the loop reports as an incomplete turn.
_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "model_context_window_exceeded": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "content_filtered": StopReason.CONTENT_FILTERED,
    "guardrail_intervened": StopReason.CONTENT_FILTERED,
}


class BedrockProvider(LLMProvider):
    """Adapts the neutral agent types to the Bedrock Converse API."""

    def __init__(self, *, client: Any = None, model_id: str | None = None):
        self._client = client or bedrock_runtime_client()
        self.model_id = model_id or MODEL_ID
        self.prompt_caching = PROMPT_CACHING

    # -- public surface ---------------------------------------------------

    def render_tools(self, tools: list[Tool]) -> dict:
        """Render tools to a Converse ``toolConfig`` dict."""
        return {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": {"json": tool.input_schema},
                    }
                }
                for tool in tools
            ]
        }

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int,
        temperature: float,
    ) -> AssistantTurn:
        # This call is the run's unit of silence -- report before making it.
        heartbeat.touch()
        inference_config: dict = {"maxTokens": max_tokens}
        if _accepts_sampling_params(self.model_id):
            inference_config["temperature"] = temperature
        system: list[dict] = [{"text": system_prompt}]
        if self.prompt_caching:
            # A cache point after `system` caches the whole preceding prefix --
            # tools render before system on Bedrock, so this covers tools+system,
            # the bytes that repeat unchanged on every turn.
            system.append({"cachePoint": {"type": "default"}})
        kwargs: dict = {
            "modelId": self.model_id,
            "system": system,
            "messages": self._render_messages(messages, cache_last=self.prompt_caching),
            "inferenceConfig": inference_config,
        }
        if rendered_tools and rendered_tools.get("tools"):
            kwargs["toolConfig"] = rendered_tools

        try:
            response = self._client.converse(**kwargs)
        except Exception as e:
            logger.exception("Bedrock complete failed")
            raise ProviderError(f"Bedrock complete failed: {e}") from e

        self._log_usage(response)
        return self._parse_turn(response)

    # -- private helpers --------------------------------------------------

    def _render_messages(
        self, messages: list[Message], *, cache_last: bool = False
    ) -> list[dict]:
        rendered = [
            {"role": m.role, "content": [self._render_block(b) for b in m.content]}
            for m in messages
        ]
        if cache_last and rendered:
            # Cache the conversation prefix through the latest turn; the next
            # turn re-sends these same messages as a prefix and reads the cache.
            rendered[-1]["content"].append({"cachePoint": {"type": "default"}})
        return rendered

    def _log_usage(self, response: dict) -> None:
        """Log Converse token usage so cache hits are observable.

        After the first turn, ``cache_read`` should dominate ``input`` if caching
        is landing; a persistent ``cache_read=0`` means a silent invalidator.
        """
        usage = response.get("usage") or {}
        logger.info(
            "bedrock converse usage: input=%s cache_read=%s cache_write=%s output=%s",
            usage.get("inputTokens"),
            usage.get("cacheReadInputTokens"),
            usage.get("cacheWriteInputTokens"),
            usage.get("outputTokens"),
        )

    def _render_block(self, block: Any) -> dict:
        if isinstance(block, TextBlock):
            return {"text": block.text}
        if isinstance(block, ThinkingBlock):
            # Replayed byte-for-byte: reasoning text is signed, and a turn
            # replayed with it edited or missing fails validation.
            return {"reasoningContent": dict(block.data)}
        if isinstance(block, ToolUseBlock):
            return {
                "toolUse": {
                    "toolUseId": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            }
        if isinstance(block, ToolResultBlock):
            tool_result: dict = {
                "toolUseId": block.tool_use_id,
                "content": [{"json": block.content}],
            }
            if block.is_error:
                tool_result["status"] = "error"
            return {"toolResult": tool_result}
        raise TypeError(f"unrenderable block: {block!r}")

    def _parse_turn(self, response: dict) -> AssistantTurn:
        message = (response.get("output") or {}).get("message")
        if not message:
            raise ProviderError("Invalid Bedrock response: missing output message")

        text_blocks: list[TextBlock] = []
        thinking_blocks: list[ThinkingBlock] = []
        tool_calls: list[ToolUseBlock] = []
        # The turn in Converse's own order -- what the loop replays. The grouped
        # lists are views onto these same blocks.
        content_blocks: list[Block] = []
        for block in message.get("content", []):
            parsed: Block
            if "text" in block:
                parsed = TextBlock(text=block["text"])
                text_blocks.append(parsed)
            elif "reasoningContent" in block:
                # Kept whole (``reasoningText`` with its signature, or the
                # ``redactedContent`` blob) so the next turn can replay it.
                parsed = ThinkingBlock(data=block["reasoningContent"])
                thinking_blocks.append(parsed)
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                parsed = ToolUseBlock(
                    id=tool_use["toolUseId"],
                    name=tool_use["name"],
                    input=tool_use.get("input") or {},
                )
                tool_calls.append(parsed)
            else:
                continue
            content_blocks.append(parsed)

        stop_reason = _STOP_REASONS.get(response.get("stopReason"), StopReason.OTHER)
        return AssistantTurn(
            text_blocks=text_blocks,
            thinking_blocks=thinking_blocks,
            tool_calls=tool_calls,
            content_blocks=content_blocks,
            stop_reason=stop_reason,
            raw=response,
            usage=self._parse_usage(response),
            latency_ms=(response.get("metrics") or {}).get("latencyMs"),
        )

    def _parse_usage(self, response: dict) -> TurnUsage | None:
        usage = response.get("usage")
        if not usage:
            return None
        return TurnUsage(
            input_tokens=usage.get("inputTokens"),
            output_tokens=usage.get("outputTokens"),
            cache_read_tokens=usage.get("cacheReadInputTokens"),
            cache_write_tokens=usage.get("cacheWriteInputTokens"),
        )
