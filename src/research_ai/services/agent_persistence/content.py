"""Agent-specific serialization policies for persisted message content."""

import json
import logging
from typing import Any

from research_ai.services.agent.types import Message, serialize_messages

logger = logging.getLogger(__name__)

MAX_TRACE_MESSAGE_BYTES = 128 * 1024
MAX_BLOCK_PAYLOAD_BYTES = 48 * 1024
MAX_CONTEXT_MESSAGE_BYTES = 512 * 1024
_PREVIEW_CHARS = 2048
_FINAL_OUTPUT_SUFFIX = "\n[Response truncated for durable storage.]"
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


def serialize_context_message(
    message: Message,
) -> tuple[list[dict], dict, bool, int]:
    """Keep complete resumable context or replace it with valid text.

    Provider continuation state is bounded together with the content because
    both are required to resume a provider turn correctly. Neither should ever
    reach the limit: model output is capped by ``max_tokens`` and tool results
    by ``MAX_TOOL_RESULT_BYTES``, so a message this large means one of those
    bounds is missing rather than that a conversation grew. The row still has
    to hold something, so it holds text the provider accepts -- a compacted
    marker, and no state describing content that is no longer there.
    """
    serialized = serialize_messages([message])[0]
    payload = {
        "content": serialized["content"],
        "provider_state": serialized.get("provider_state") or {},
    }
    safe_payload, was_replaced, original_size = _bounded_json(
        payload,
        limit=MAX_CONTEXT_MESSAGE_BYTES,
    )
    if not was_replaced:
        return (
            safe_payload["content"],
            safe_payload["provider_state"],
            False,
            original_size,
        )
    logger.error(
        "agent context message of %d bytes exceeded the durable row limit; "
        "the conversation is no longer resumable from this turn",
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
