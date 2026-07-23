"""Agent-specific serialization policies for persisted message content."""

from typing import Any

from research_ai.services.agent.types import Message, serialize_messages
from utils.json import bounded_json_value, json_size_bytes

MAX_TRACE_MESSAGE_BYTES = 128 * 1024
MAX_BLOCK_PAYLOAD_BYTES = 48 * 1024
MAX_TRACE_TEXT_BYTES = 32 * 1024
MAX_CONTEXT_MESSAGE_BYTES = 512 * 1024
MAX_CONTEXT_BLOCK_PAYLOAD_BYTES = 128 * 1024
MAX_CONTEXT_TEXT_BYTES = 128 * 1024
_PREVIEW_CHARS = 2048
_CONTEXT_TEXT_SUFFIX = "\n[Earlier text compacted for durable model context.]"
_FINAL_OUTPUT_SUFFIX = "\n[Response truncated for durable storage.]"


def bounded_payload(
    value: Any, *, limit: int = MAX_BLOCK_PAYLOAD_BYTES
) -> tuple[Any, bool, int]:
    """Apply agent payload limits to arbitrary tool or execution data."""
    return bounded_json_value(
        value,
        max_bytes=limit,
        preview_chars=_PREVIEW_CHARS,
    )


def _truncate_utf8(text: str, max_bytes: int, *, suffix: str) -> tuple[str, bool, int]:
    """Truncate text on a UTF-8 boundary and report its original byte size."""
    encoded = text.encode("utf-8")
    original_size = len(encoded)
    if original_size <= max_bytes:
        return text, False, original_size

    suffix_bytes = suffix.encode("utf-8")
    available = max(0, max_bytes - len(suffix_bytes))
    prefix = encoded[:available].decode("utf-8", errors="ignore")
    return prefix + suffix, True, original_size


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


def _serialize_trace_text_block(block: dict) -> tuple[dict, bool, int]:
    text = str(block.get("text") or "")
    text, was_truncated, original_size = _truncate_utf8(
        text,
        MAX_TRACE_TEXT_BYTES,
        suffix="…",
    )
    if was_truncated:
        block["text"] = text
        block["_truncated"] = True
    return block, was_truncated, original_size


def _serialize_trace_payload_block(
    block: dict,
    payload_field: str,
) -> tuple[dict, bool, int]:
    payload, was_truncated, original_size = bounded_payload(
        block.get(payload_field) or {}
    )
    block[payload_field] = payload
    return block, was_truncated, original_size


def _serialize_trace_block(raw_block: Any) -> tuple[dict, bool, int]:
    block = (
        dict(raw_block)
        if isinstance(raw_block, dict)
        else {"type": "unknown", "value": raw_block}
    )
    block_type = block.get("type")
    if block_type == "text":
        return _serialize_trace_text_block(block)

    payload_field = {
        "tool_use": "input",
        "tool_result": "content",
    }.get(block_type)
    if payload_field:
        return _serialize_trace_payload_block(block, payload_field)

    payload, was_truncated, original_size = bounded_payload(block)
    if not isinstance(payload, dict):
        payload = {"type": "unknown", "value": payload}
        was_truncated = True
    payload.setdefault("type", str(block_type or "unknown"))
    return payload, was_truncated, original_size


def serialize_trace_message(message: Message) -> tuple[list[dict], bool, int]:
    """Serialize one protocol message while enforcing a hard row-size budget."""
    block_count = len(message.content)
    safe_blocks = serialize_messages([message])[0]["content"]
    original_size = 0
    omitted_blocks = block_count - len(safe_blocks)
    truncated = omitted_blocks > 0
    bounded_blocks: list[dict] = []

    for raw_block in safe_blocks:
        block, block_was_truncated, block_size = _serialize_trace_block(raw_block)
        original_size += block_size
        truncated = truncated or block_was_truncated

        candidate = [*bounded_blocks, block]
        if json_size_bytes(candidate) > MAX_TRACE_MESSAGE_BYTES:
            omitted_blocks += len(safe_blocks) - len(bounded_blocks)
            truncated = True
            break
        bounded_blocks.append(block)

    if omitted_blocks:
        bounded_blocks.append(
            {
                "type": "trace_truncated",
                "_truncated": True,
                "omitted_blocks": omitted_blocks,
            }
        )
    if json_size_bytes(bounded_blocks) > MAX_TRACE_MESSAGE_BYTES:
        bounded_blocks = [
            {
                "type": "trace_truncated",
                "_truncated": True,
                "omitted_blocks": block_count,
            }
        ]
        truncated = True

    return bounded_blocks, truncated, original_size


def serialize_context_message(
    message: Message,
) -> tuple[list[dict], bool, int | None]:
    """Serialize resumable context with explicit, type-safe compaction.

    Context rows are retained independently from observational traces. Tool
    payloads are replaced by structured previews when large; if the complete
    typed message still exceeds its row budget, it becomes a normal text block
    explaining that the historical message was compacted. The result therefore
    always remains deserializable and provider-neutral.
    """
    raw_blocks = serialize_messages([message])[0]["content"]
    original_size = 0
    compacted = False
    context_blocks: list[dict] = []

    for raw_block in raw_blocks:
        block = dict(raw_block)
        block_type = block["type"]
        if block_type == "text":
            text = str(block.get("text") or "")
            text, text_was_compacted, text_size = _truncate_utf8(
                text,
                MAX_CONTEXT_TEXT_BYTES,
                suffix=_CONTEXT_TEXT_SUFFIX,
            )
            original_size += text_size
            if text_was_compacted:
                block["text"] = text
                compacted = True
        elif block_type == "tool_use":
            payload, was_compacted, payload_size = bounded_payload(
                block.get("input") or {},
                limit=MAX_CONTEXT_BLOCK_PAYLOAD_BYTES,
            )
            block["input"] = payload
            original_size += payload_size
            compacted = compacted or was_compacted
        elif block_type == "tool_result":
            payload, was_compacted, payload_size = bounded_payload(
                block.get("content") or {},
                limit=MAX_CONTEXT_BLOCK_PAYLOAD_BYTES,
            )
            block["content"] = payload
            original_size += payload_size
            compacted = compacted or was_compacted
        context_blocks.append(block)

    if json_size_bytes(context_blocks) > MAX_CONTEXT_MESSAGE_BYTES:
        return (
            [
                {
                    "type": "text",
                    "text": (
                        "[Earlier model-context message compacted because it "
                        "exceeded the durable row limit.]"
                    ),
                }
            ],
            True,
            original_size,
        )
    return context_blocks, compacted, original_size
