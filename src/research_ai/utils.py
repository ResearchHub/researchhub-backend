import json
import re
from typing import Any

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def trimmed_str(value: Any, *, max_len: int | None = None) -> str:
    """``str(value)``, strip, optional truncation; empty string for ``None``."""
    if value is None:
        return ""
    s = str(value).strip()
    if max_len is not None:
        s = s[:max_len]
    return s


def extract_json_object(raw: str | None) -> dict:
    """Extract the first JSON object from a raw LLM completion.

    LLMs wrap JSON in ```` ```json ```` fences or surrounding prose despite being
    told not to. Tries the whole (trimmed) string, then any fenced block, then
    the widest ``{...}`` span -- returning the first that parses to a ``dict``.

    Raises ``ValueError`` when no JSON object can be parsed, so callers can treat
    an unparseable reply as a (best-effort) failure.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM response; no JSON object to parse")

    candidates: list[str] = [text]
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj

    raise ValueError(f"no JSON object in LLM response: {raw!r}")
