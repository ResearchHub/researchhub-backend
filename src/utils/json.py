"""Helpers for safely bounding arbitrary values before JSON persistence."""

import json
import math
from typing import Any


def json_size_bytes(value: Any) -> int:
    """Return the UTF-8 size of a compact, deterministic JSON representation."""
    return len(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _try_stringify(value: Any) -> str | None:
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - this is the final serialization fallback
        return None


def _serialization_error(value: Any) -> dict[str, bool | str]:
    """Return a JSON-compatible marker for a failed ``str()`` conversion."""
    return {
        "_serialization_error": True,
        "type": type(value).__name__,
    }


def _add_truncated_items_marker(result: dict[str, Any], omitted_items: int) -> None:
    """Add a truncation marker without overwriting a retained dictionary key."""
    marker_key = "_truncated_items"
    while marker_key in result:
        marker_key = f"_{marker_key}"
    result[marker_key] = omitted_items


def _json_safe(
    value: Any,
    *,
    depth: int,
    max_string_bytes: int,
    max_collection_items: int,
    max_nesting_depth: int,
    preview_chars: int,
) -> tuple[Any, bool]:
    """Make arbitrary data JSON-safe without traversing it without bounds."""
    if depth >= max_nesting_depth:
        return {"_truncated": True, "reason": "maximum nesting depth"}, True
    if value is None or isinstance(value, (bool, int)):
        return value, False
    if isinstance(value, float):
        if math.isfinite(value):
            return value, False
        stringified = _try_stringify(value)
        if stringified is None:
            return _serialization_error(value), True
        return stringified, False
    if isinstance(value, str):
        size_bytes = len(value.encode("utf-8"))
        if size_bytes > max_string_bytes:
            return (
                {
                    "_truncated": True,
                    "original_size_bytes": size_bytes,
                    "preview": value[:preview_chars],
                },
                True,
            )
        return value, False
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        was_lossy = False
        for index, (key, item) in enumerate(value.items()):
            if index >= max_collection_items:
                _add_truncated_items_marker(
                    result,
                    len(value) - max_collection_items,
                )
                was_lossy = True
                break
            safe_key = _try_stringify(key)
            if safe_key is None:
                safe_key = f"<unserializable {type(key).__name__}>"
                was_lossy = True
            safe_item, item_was_lossy = _json_safe(
                item,
                depth=depth + 1,
                max_string_bytes=max_string_bytes,
                max_collection_items=max_collection_items,
                max_nesting_depth=max_nesting_depth,
                preview_chars=preview_chars,
            )
            result[safe_key] = safe_item
            was_lossy = was_lossy or item_was_lossy
        return result, was_lossy
    if isinstance(value, (list, tuple)):
        result = []
        was_lossy = False
        for item in value[:max_collection_items]:
            safe_item, item_was_lossy = _json_safe(
                item,
                depth=depth + 1,
                max_string_bytes=max_string_bytes,
                max_collection_items=max_collection_items,
                max_nesting_depth=max_nesting_depth,
                preview_chars=preview_chars,
            )
            result.append(safe_item)
            was_lossy = was_lossy or item_was_lossy
        if len(value) > max_collection_items:
            result.append({"_truncated_items": len(value) - max_collection_items})
            was_lossy = True
        return result, was_lossy
    stringified = _try_stringify(value)
    if stringified is None:
        return _serialization_error(value), True
    return _json_safe(
        stringified,
        depth=depth,
        max_string_bytes=max_string_bytes,
        max_collection_items=max_collection_items,
        max_nesting_depth=max_nesting_depth,
        preview_chars=preview_chars,
    )


def _reported_original_size(value: Any, fallback: int) -> int:
    largest = fallback
    if isinstance(value, dict):
        marker_size = value.get("original_size_bytes")
        if isinstance(marker_size, int):
            largest = max(largest, marker_size)
        for item in value.values():
            largest = max(largest, _reported_original_size(item, 0))
    elif isinstance(value, list):
        for item in value:
            largest = max(largest, _reported_original_size(item, 0))
    return largest


def bounded_json_value(
    value: Any,
    *,
    max_bytes: int,
    max_string_bytes: int | None = None,
    max_collection_items: int = 500,
    max_nesting_depth: int = 20,
    preview_chars: int = 2048,
) -> tuple[Any, bool, int]:
    """Return a JSON-safe value bounded by a serialized byte budget.

    The tuple contains the safe value, whether information was omitted or an
    unstringable value was replaced by an error marker, and the best available
    original-size measurement. Ordinary ``str()`` coercion of supported fallback
    values does not set the boolean. Traversal itself is bounded by the
    collection and nesting limits.
    """
    if max_bytes < json_size_bytes({"_truncated": True}):
        raise ValueError("max_bytes is too small for a truncation marker")
    if max_string_bytes is None:
        max_string_bytes = max_bytes
    if (
        min(
            max_string_bytes,
            max_collection_items,
            max_nesting_depth,
            preview_chars,
        )
        < 1
    ):
        raise ValueError("JSON bounds must be positive")

    safe, was_lossy = _json_safe(
        value,
        depth=0,
        max_string_bytes=max_string_bytes,
        max_collection_items=max_collection_items,
        max_nesting_depth=max_nesting_depth,
        preview_chars=preview_chars,
    )
    encoded_size = json_size_bytes(safe)
    original_size = _reported_original_size(safe, encoded_size)
    if original_size <= max_bytes:
        return safe, was_lossy, original_size

    marker = {
        "_truncated": True,
        "original_size_bytes": original_size,
        "preview": json.dumps(
            safe,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )[:preview_chars],
    }
    if json_size_bytes(marker) > max_bytes:
        marker.pop("preview")
    if json_size_bytes(marker) > max_bytes:
        marker = {"_truncated": True}
    return marker, True, original_size
