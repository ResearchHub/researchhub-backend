from typing import Any


def trimmed_str(value: Any, *, max_len: int | None = None) -> str:
    """``str(value)``, strip, optional truncation; empty string for ``None``."""
    if value is None:
        return ""
    s = str(value).strip()
    if max_len is not None:
        s = s[:max_len]
    return s
