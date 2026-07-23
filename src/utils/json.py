"""Helpers for validating and bounding JSON values before persistence."""

import json
from typing import Any


def _encode_json(value: Any) -> str:
    """Return the compact, deterministic JSON representation of a value."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def json_size_bytes(value: Any) -> int:
    """Return the UTF-8 size of a compact, deterministic JSON representation."""
    return len(_encode_json(value).encode("utf-8"))


def _marker_within_limit(
    marker: dict[str, Any],
    *,
    max_bytes: int,
    fallback: dict[str, bool],
) -> dict[str, Any]:
    """Return a detailed marker when it fits, otherwise its minimal fallback."""
    return marker if json_size_bytes(marker) <= max_bytes else fallback


def bounded_json_value(
    value: Any,
    *,
    max_bytes: int,
    preview_chars: int = 2048,
) -> tuple[Any, bool, int]:
    """Return strict JSON data bounded by its serialized UTF-8 size.

    The tuple contains the persisted value, whether it was replaced, and the
    original serialized size when measurable. Inputs must already use native
    JSON types; unsupported values are replaced rather than coerced.
    """
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if (
        not isinstance(preview_chars, int)
        or isinstance(preview_chars, bool)
        or preview_chars < 1
    ):
        raise ValueError("preview_chars must be a positive integer")

    minimal_marker = {"_truncated": True}
    if json_size_bytes(minimal_marker) > max_bytes:
        raise ValueError("max_bytes is too small for a truncation marker")

    try:
        encoded = _encode_json(value)
        encoded_bytes = encoded.encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        marker = _marker_within_limit(
            {
                "_serialization_error": True,
                "error": type(error).__name__,
                "type": type(value).__name__,
            },
            max_bytes=max_bytes,
            fallback=minimal_marker,
        )
        return marker, True, 0

    original_size = len(encoded_bytes)
    if original_size > max_bytes:
        marker = _marker_within_limit(
            {
                "_truncated": True,
                "original_size_bytes": original_size,
                "preview": encoded[:preview_chars],
            },
            max_bytes=max_bytes,
            fallback=minimal_marker,
        )
        return marker, True, original_size

    try:
        decoded = json.loads(encoded)
    except (json.JSONDecodeError, RecursionError) as error:
        marker = _marker_within_limit(
            {
                "_serialization_error": True,
                "error": type(error).__name__,
                "type": type(value).__name__,
            },
            max_bytes=max_bytes,
            fallback=minimal_marker,
        )
        return marker, True, original_size
    if decoded != value:
        marker = _marker_within_limit(
            {
                "_serialization_error": True,
                "error": "non_native_json_type",
                "type": type(value).__name__,
            },
            max_bytes=max_bytes,
            fallback=minimal_marker,
        )
        return marker, True, original_size

    return decoded, False, original_size
