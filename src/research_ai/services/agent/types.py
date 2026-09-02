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
    # The provider paused a turn mid-flight after running its own server-side
    # tools (it caps how many it will run per turn). Nothing failed and nothing
    # is owed by the caller: the turn resumes by sending the conversation back
    # with the paused assistant turn appended and no new user turn.
    PAUSE_TURN = "pause_turn"
    OTHER = "other"


@dataclass(frozen=True)
class TextBlock:
    """A run of assistant or user text.

    ``data`` carries an optional provider response block verbatim. Most text
    blocks are provider-neutral and leave it unset. Providers that attach
    replay-critical metadata to assistant text (for example, Claude web-search
    citations and their encrypted indices) keep the whole block here so a
    later turn can send it back unchanged.
    """

    text: str
    data: dict | None = None
    type: str = "text"


@dataclass(frozen=True)
class ThinkingBlock:
    """A provider's reasoning block, carried through the run verbatim.

    ``data`` is the provider's own block, unmodified. Reasoning blocks are
    signed: a provider that thinks alongside tool use rejects the next turn if
    the assistant turn it replays has them dropped or edited. The agent core
    never looks inside ``data`` -- it only round-trips it, which is also why it
    is serialized whole rather than field by field.
    """

    data: dict
    type: str = "thinking"


@dataclass(frozen=True)
class ServerToolBlock:
    """A tool the *provider* ran itself, carried through the run verbatim.

    Covers both halves of a server-side tool call -- the model's request and the
    result the provider injected -- as one opaque payload each. Unlike a
    ``ToolUseBlock``, none of this is ever dispatched: the provider ran the tool
    inside the same turn and handed the result back already, so the agent core
    only replays these blocks, unedited and in their original position. The
    provider validates the request/result pairing when the turn is replayed, so
    a dropped or reordered block fails the next turn.
    """

    data: dict
    type: str = "server_tool"


@dataclass(frozen=True)
class ToolUseBlock:
    """The model's request to call a tool. ``id`` correlates with the result.

    ``data`` optionally carries the provider response block verbatim. Most tool
    calls are provider-neutral and leave it unset. Providers that attach
    replay-critical metadata to a call keep the whole block here; for example,
    Claude identifies calls made from code execution with a ``caller`` field.
    """

    id: str
    name: str
    input: dict
    data: dict | None = None
    type: str = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock:
    """The result of a tool call, fed back to the model on the next turn."""

    tool_use_id: str
    content: dict
    is_error: bool = False
    type: str = "tool_result"


# A content block is one of the five block types above.
Block = TextBlock | ThinkingBlock | ServerToolBlock | ToolUseBlock | ToolResultBlock


@dataclass(frozen=True)
class Message:
    """One conversation turn plus opaque provider continuation state.

    ``provider_state`` is request-level state that cannot live in a content
    block. The agent core carries it without interpreting it so a provider can
    resume a turn across calls. Claude's code-execution container identifier is
    one example.
    """

    role: str
    content: list[Block]
    provider_state: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TurnUsage:
    """Normalized billable accounting for a single model turn.

    Each adapter maps its provider's usage shape onto these counters; a
    counter the provider did not report stays ``None`` (distinct from a
    reported zero).
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    web_search_requests: int | None = None


@dataclass(frozen=True)
class TextStreamDelta:
    """One user-visible text fragment from an in-flight provider turn."""

    block_index: int
    text: str
    type: str = "text_delta"


@dataclass(frozen=True)
class ThinkingStreamDelta:
    """One readable reasoning-summary fragment from an in-flight turn.

    Providers must never use this event for opaque signatures, redacted
    blocks, or encrypted continuation state.
    """

    block_index: int
    text: str
    type: str = "thinking_delta"


@dataclass(frozen=True)
class ToolUseStreamStart:
    """A tool-use block opened in an in-flight provider turn.

    Emitted when the model begins composing a tool call -- client-side or
    server-side -- so an observer can show what the model is about to do
    while the (often long) arguments stream in.
    """

    block_index: int
    name: str
    type: str = "tool_use_start"


@dataclass(frozen=True)
class ToolInputStreamDelta:
    """One fragment of a tool call's JSON arguments from an in-flight turn.

    ``partial_json`` is a raw slice of the arguments document; fragments
    concatenate into valid JSON only once the block completes.
    """

    block_index: int
    partial_json: str
    type: str = "input_json_delta"


@dataclass(frozen=True)
class StreamReset:
    """Discard the current preview before a provider replaces an attempt."""

    type: str = "stream_reset"


ProviderStreamEvent = (
    TextStreamDelta
    | ThinkingStreamDelta
    | ToolUseStreamStart
    | ToolInputStreamDelta
    | StreamReset
)


@dataclass(frozen=True)
class AssistantTurn:
    """A parsed model response: text, tool calls, stop reason, and raw payload.

    ``raw`` keeps the untouched provider response for logging/debugging; it is
    intentionally excluded from JSON serialization of conversations. ``usage``
    and ``latency_ms`` are per-turn metadata for recorders; ``None`` when the
    provider does not report them. ``thinking_blocks`` holds the turn's
    reasoning blocks (empty for providers that do not return any).

    ``content_blocks`` is the turn's *whole* content in the provider's original
    order, and is what the loop replays as the assistant message. The grouped
    lists above are views onto the same blocks, for the loop's own logic
    (dispatching calls, tracing reasoning) -- they cannot be concatenated back
    into a faithful turn, because order carries meaning: reasoning blocks lead,
    and a server-side tool's result must stay immediately after its request. An
    adapter that leaves it empty falls back to the grouped order.

    ``stop_details`` is the provider's structured account of *why* the turn
    stopped, carried verbatim. Only a content-filtered turn has one, and it is
    the only thing that says which classifier fired: a refusal arrives as a
    successful response with empty content, so without these details the
    failure is indistinguishable from any other empty turn.
    """

    text_blocks: list[TextBlock]
    tool_calls: list[ToolUseBlock]
    stop_reason: StopReason
    raw: dict = field(default_factory=dict)
    stop_details: dict | None = None
    usage: TurnUsage | None = None
    latency_ms: int | None = None
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list)
    content_blocks: list[Block] = field(default_factory=list)
    provider_state: dict = field(default_factory=dict)

    @property
    def replay_content(self) -> list[Block]:
        """The assistant turn to append to the conversation, order preserved."""
        if self.content_blocks:
            return list(self.content_blocks)
        return [*self.thinking_blocks, *self.text_blocks, *self.tool_calls]

    @property
    def text(self) -> str:
        """Concatenated text of every text block in the turn."""
        return "".join(block.text for block in self.text_blocks)


def _serialize_block(block: Block) -> dict:
    if isinstance(block, TextBlock):
        serialized = {"type": "text", "text": block.text}
        if block.data is not None:
            serialized["data"] = block.data
        return serialized
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking", "data": block.data}
    if isinstance(block, ServerToolBlock):
        return {"type": "server_tool", "data": block.data}
    if isinstance(block, ToolUseBlock):
        serialized = {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
        if block.data is not None:
            serialized["data"] = block.data
        return serialized
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
        return TextBlock(text=data["text"], data=data.get("data"))
    if block_type == "thinking":
        return ThinkingBlock(data=data["data"])
    if block_type == "server_tool":
        return ServerToolBlock(data=data["data"])
    if block_type == "tool_use":
        return ToolUseBlock(
            id=data["id"],
            name=data["name"],
            input=data["input"],
            data=data.get("data"),
        )
    if block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=data["tool_use_id"],
            content=data["content"],
            is_error=data.get("is_error", False),
        )
    raise ValueError(f"unknown block type: {block_type!r}")


def serialize_messages(messages: list[Message]) -> list[dict]:
    """Render a conversation to the JSON shape an ``AgentMessage`` would store."""
    serialized = []
    for message in messages:
        item = {
            "role": message.role,
            "content": [_serialize_block(block) for block in message.content],
        }
        if message.provider_state:
            item["provider_state"] = message.provider_state
        serialized.append(item)
    return serialized


def deserialize_messages(data: list[dict]) -> list[Message]:
    """Rebuild a conversation from its ``serialize_messages`` JSON shape."""
    return [
        Message(
            role=m["role"],
            content=[_deserialize_block(b) for b in m["content"]],
            provider_state=m.get("provider_state") or {},
        )
        for m in data
    ]
