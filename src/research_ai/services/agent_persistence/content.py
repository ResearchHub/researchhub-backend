"""Agent-specific serialization policies for persisted message content."""

import json
from typing import Any

from research_ai.services.agent.types import Message, serialize_messages

MAX_TRACE_MESSAGE_BYTES = 128 * 1024
MAX_BLOCK_PAYLOAD_BYTES = 48 * 1024
MAX_CONTEXT_MESSAGE_BYTES = 512 * 1024
_PREVIEW_CHARS = 2048
_FINAL_OUTPUT_SUFFIX = "\n[Response truncated for durable storage.]"
_COMPACTED_BLOCK_TEXT = "[Text omitted because it exceeded the durable row limit.]"
_COMPACTED_MESSAGE_TEXT = (
    "[Earlier model-context message compacted because it exceeded the durable row "
    "limit.]"
)


def _encode_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def json_size_bytes(value: Any) -> int:
    """Return the compact JSON size used by persistence limits."""
    return len(_encode_json(value).encode("utf-8"))


def _bounded_json(value: Any, *, limit: int) -> tuple[Any, bool, int]:
    """Normalize one JSON value and replace invalid or oversized data."""
    try:
        encoded = _encode_json(value)
        normalized = json.loads(encoded)
    except (TypeError, ValueError, RecursionError):
        return {"_serialization_error": True}, True, 0

    original_size = len(encoded.encode("utf-8"))
    if normalized != value:
        return {"_serialization_error": True}, True, original_size
    if original_size > limit:
        return (
            {
                "_truncated": True,
                "original_size_bytes": original_size,
                "preview": encoded[:_PREVIEW_CHARS],
            },
            True,
            original_size,
        )
    return normalized, False, original_size


def bounded_payload(value: Any) -> tuple[Any, bool, int]:
    """Apply the persistence limit to arbitrary agent metadata."""
    return _bounded_json(value, limit=MAX_BLOCK_PAYLOAD_BYTES)


def serialize_trace_message(message: Message) -> tuple[list[dict], bool, int]:
    """Keep a complete trace message or replace it with one marker."""
    blocks = serialize_messages([message])[0]["content"]
    safe_blocks, was_replaced, original_size = _bounded_json(
        blocks,
        limit=MAX_TRACE_MESSAGE_BYTES,
    )
    if not was_replaced:
        return safe_blocks, False, original_size
    return (
        [
            {
                "type": "text",
                "text": (
                    "[Trace message omitted because it exceeded the durable row limit.]"
                ),
                "_truncated": True,
                "omitted_blocks": len(blocks),
            }
        ],
        True,
        original_size,
    )


def _compacted_block(block: dict, original_size: int) -> dict:
    """Drop one block's payload while keeping the fields replay depends on.

    Tool identifiers have to survive compaction. A provider rejects the next
    turn outright when a ``tool_result`` no longer answers a ``tool_use`` in
    the turn before it, so discarding the block would make the conversation
    unresumable rather than merely lossy. Signed reasoning and server-tool
    blocks keep their position for the same reason, but their payload is
    opaque and cannot be shortened without invalidating it.
    """
    marker = {"_truncated": True, "original_size_bytes": original_size}
    block_type = block["type"]
    if block_type == "tool_use":
        return {
            "type": "tool_use",
            "id": block["id"],
            "name": block["name"],
            "input": marker,
        }
    if block_type == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": block["tool_use_id"],
            "content": marker,
            "is_error": block.get("is_error", False),
        }
    if block_type == "text":
        return {"type": "text", "text": _COMPACTED_BLOCK_TEXT}
    return {"type": block_type, "data": marker}


def _compact_context_content(blocks: list[dict], block_limit: int) -> list[dict]:
    """Bound every block against ``block_limit``, preserving message shape."""
    compacted = []
    for block in blocks:
        safe_block, was_replaced, block_size = _bounded_json(block, limit=block_limit)
        compacted.append(
            _compacted_block(block, block_size) if was_replaced else safe_block
        )
    return compacted


def serialize_context_message(
    message: Message,
) -> tuple[list[dict], dict, bool, int]:
    """Keep complete resumable context, or compact it without breaking replay.

    Provider continuation state is bounded together with the content because
    both are required to resume a provider turn correctly. An oversized message
    is compacted block by block -- first only the blocks that are individually
    too large, then all of them -- so tool-call correlation and block structure
    survive the row limit. Only a message still too large after that degrades
    to a single text block, which also drops the provider state because it no
    longer corresponds to the stored content.
    """
    serialized = serialize_messages([message])[0]
    content = serialized["content"]
    provider_state = serialized.get("provider_state") or {}
    safe_payload, was_replaced, original_size = _bounded_json(
        {"content": content, "provider_state": provider_state},
        limit=MAX_CONTEXT_MESSAGE_BYTES,
    )
    if not was_replaced:
        return (
            safe_payload["content"],
            safe_payload["provider_state"],
            False,
            original_size,
        )

    for block_limit in (MAX_BLOCK_PAYLOAD_BYTES, 0):
        candidate, still_oversized, _size = _bounded_json(
            {
                "content": _compact_context_content(content, block_limit),
                "provider_state": provider_state,
            },
            limit=MAX_CONTEXT_MESSAGE_BYTES,
        )
        if not still_oversized:
            return (
                candidate["content"],
                candidate["provider_state"],
                True,
                original_size,
            )

    return (
        [{"type": "text", "text": _COMPACTED_MESSAGE_TEXT}],
        {},
        True,
        original_size,
    )


def serialize_final_output(text: str) -> tuple[dict[str, Any], bool, int]:
    """Keep final output repairable while enforcing the execution-row budget."""
    original_size = len(text.encode("utf-8"))
    output: dict[str, Any] = {"text": text}
    if json_size_bytes(output) <= MAX_TRACE_MESSAGE_BYTES:
        return output, False, original_size

    base: dict[str, Any] = {
        "_truncated": True,
        "original_size_bytes": original_size,
    }
    low = 0
    high = len(text)
    best = _FINAL_OUTPUT_SUFFIX
    while low <= high:
        midpoint = (low + high) // 2
        candidate_text = text[:midpoint] + _FINAL_OUTPUT_SUFFIX
        candidate = {**base, "text": candidate_text}
        if json_size_bytes(candidate) <= MAX_TRACE_MESSAGE_BYTES:
            best = candidate_text
            low = midpoint + 1
        else:
            high = midpoint - 1
    return {**base, "text": best}, True, original_size
