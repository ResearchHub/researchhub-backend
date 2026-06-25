"""Neutral, provider-agnostic types for the agent core.

These dataclasses are the lingua franca of the agent loop: the loop and the
toolset only ever speak in terms of ``Message``/``*Block``/``AssistantTurn``,
and each provider adapter is responsible for rendering them to (and parsing
them from) its own wire format. Keeping the core neutral is what lets a later
PR run the same conversation through multiple providers (e.g. a judge panel).

Every block carries a ``type`` discriminator and is JSON round-trippable via
``serialize_messages`` / ``deserialize_messages`` -- that JSON shape is exactly
what a future ``AgentMessage.JSONField`` will persist. No Django models here.

Id-correlation invariant: a ``ToolUseBlock.id`` emitted by the assistant is
echoed back as the ``ToolResultBlock.tool_use_id`` of its result. Adapters must
preserve this mapping when rendering to/from provider formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class StopReason(StrEnum):
    """Why a single model turn ended (provider stop reasons, normalized)."""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    CONTENT_FILTERED = "content_filtered"
    OTHER = "other"


@dataclass(frozen=True)
class TextBlock:
    """A run of assistant or user text."""

    text: str
    type: str = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    """The model's request to call a tool. ``id`` correlates with the result."""

    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock:
    """The result of a tool call, fed back to the model on the next turn."""

    tool_use_id: str
    content: dict
    is_error: bool = False
    type: str = "tool_result"


# A content block is one of the three block types above.
Block = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass(frozen=True)
class Message:
    """One conversation turn: a role plus an ordered list of content blocks."""

    role: str
    content: list[Block]


@dataclass(frozen=True)
class AssistantTurn:
    """A parsed model response: text, tool calls, stop reason, and raw payload.

    ``raw`` keeps the untouched provider response for logging/debugging; it is
    intentionally excluded from JSON serialization of conversations.
    """

    text_blocks: list[TextBlock]
    tool_calls: list[ToolUseBlock]
    stop_reason: StopReason
    raw: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Concatenated text of every text block in the turn."""
        return "".join(block.text for block in self.text_blocks)


def _serialize_block(block: Block) -> dict:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    raise TypeError(f"unserializable block: {block!r}")


def _deserialize_block(data: dict) -> Block:
    block_type = data.get("type")
    if block_type == "text":
        return TextBlock(text=data["text"])
    if block_type == "tool_use":
        return ToolUseBlock(id=data["id"], name=data["name"], input=data["input"])
    if block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=data["tool_use_id"],
            content=data["content"],
            is_error=data.get("is_error", False),
        )
    raise ValueError(f"unknown block type: {block_type!r}")


def serialize_messages(messages: list[Message]) -> list[dict]:
    """Render a conversation to the JSON shape an ``AgentMessage`` would store."""
    return [
        {"role": m.role, "content": [_serialize_block(b) for b in m.content]}
        for m in messages
    ]


def deserialize_messages(data: list[dict]) -> list[Message]:
    """Rebuild a conversation from its ``serialize_messages`` JSON shape."""
    return [
        Message(
            role=m["role"],
            content=[_deserialize_block(b) for b in m["content"]],
        )
        for m in data
    ]
