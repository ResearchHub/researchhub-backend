"""Bedrock Converse adapter.

Wraps the timeout-configured Converse client from ``utils.aws`` and renders the
neutral agent types to/from the Converse wire format. This is a faithful port of
the proven single-provider tool loop (``BedrockLLMService.run_tool_loop``),
split into the provider-agnostic ``LLMProvider`` shape.
"""

import logging
from typing import Any

from django.conf import settings

from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from utils.aws import bedrock_runtime_client

logger = logging.getLogger(__name__)

# Default generator model. Bedrock requires the cross-region inference profile
# (the ``us.`` prefix); the bare ``anthropic.claude-opus-4-8`` is provisioned-
# throughput only. Override per environment via RESEARCH_AI_GENERATOR_MODEL_ID.
_DEFAULT_MODEL_ID = "us.anthropic.claude-opus-4-8"

# Opus 4.7+ and Fable reject sampling params (temperature/top_p/top_k) with a
# 400 ("`temperature` is deprecated for this model"). Match by substring so the
# provider omits them for those models.
_NO_SAMPLING_PARAMS = ("opus-4-7", "opus-4-8", "fable")


def _accepts_sampling_params(model_id: str) -> bool:
    mid = model_id.lower()
    return not any(tag in mid for tag in _NO_SAMPLING_PARAMS)


# Bedrock Converse ``stopReason`` -> neutral ``StopReason``.
_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "content_filtered": StopReason.CONTENT_FILTERED,
    "guardrail_intervened": StopReason.CONTENT_FILTERED,
}


class BedrockProvider(LLMProvider):
    """Adapts the neutral agent types to the Bedrock Converse API."""

    def __init__(self, *, client: Any = None, model_id: str | None = None):
        self._client = client or bedrock_runtime_client()
        self.model_id = model_id or getattr(
            settings, "RESEARCH_AI_GENERATOR_MODEL_ID", _DEFAULT_MODEL_ID
        )
        # Prompt caching is the dominant cost lever for this uncached, ever-growing
        # tool loop: the tools+system prefix is byte-identical every turn and the
        # conversation only grows by appending, so cache points turn full-price
        # re-reads into ~0.1x cache reads. On by default for Claude-on-Bedrock;
        # disable per-environment if a configured model does not support it.
        self.prompt_caching = getattr(
            settings, "RESEARCH_AI_BEDROCK_PROMPT_CACHING", True
        )

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
            "messages": self._render_messages(
                messages, cache_last=self.prompt_caching
            ),
            "inferenceConfig": inference_config,
        }
        if rendered_tools and rendered_tools.get("tools"):
            kwargs["toolConfig"] = rendered_tools

        try:
            response = self._client.converse(**kwargs)
        except Exception as e:
            logger.exception("Bedrock complete failed")
            raise RuntimeError(f"Bedrock complete failed: {e}") from e

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
            "bedrock converse usage: input=%s cache_read=%s cache_write=%s "
            "output=%s",
            usage.get("inputTokens"),
            usage.get("cacheReadInputTokens"),
            usage.get("cacheWriteInputTokens"),
            usage.get("outputTokens"),
        )

    def _render_block(self, block: Any) -> dict:
        if isinstance(block, TextBlock):
            return {"text": block.text}
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
            raise RuntimeError("Invalid Bedrock response: missing output message")

        text_blocks: list[TextBlock] = []
        tool_calls: list[ToolUseBlock] = []
        for block in message.get("content", []):
            if "text" in block:
                text_blocks.append(TextBlock(text=block["text"]))
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                tool_calls.append(
                    ToolUseBlock(
                        id=tool_use["toolUseId"],
                        name=tool_use["name"],
                        input=tool_use.get("input") or {},
                    )
                )

        stop_reason = _STOP_REASONS.get(response.get("stopReason"), StopReason.OTHER)
        return AssistantTurn(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=response,
        )
