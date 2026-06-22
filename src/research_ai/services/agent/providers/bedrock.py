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
from utils import sentry
from utils.aws import bedrock_runtime_client

logger = logging.getLogger(__name__)

# Default generator model. Should eventually be Opus 4.8, but the exact Bedrock
# id must be confirmed against the AWS catalog at deploy -- keep it config-only.
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

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
        kwargs: dict = {
            "modelId": self.model_id,
            "system": [{"text": system_prompt}],
            "messages": self._render_messages(messages),
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if rendered_tools and rendered_tools.get("tools"):
            kwargs["toolConfig"] = rendered_tools

        try:
            response = self._client.converse(**kwargs)
        except Exception as e:
            sentry.log_error(e, message="Bedrock Converse API call failed")
            logger.exception("Bedrock complete failed")
            raise RuntimeError(f"Bedrock complete failed: {e}") from e

        return self._parse_turn(response)

    # -- private helpers --------------------------------------------------

    def _render_messages(self, messages: list[Message]) -> list[dict]:
        return [
            {"role": m.role, "content": [self._render_block(b) for b in m.content]}
            for m in messages
        ]

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
