"""Make source URLs clickable in blocks written by note agents."""

import re
from urllib.parse import urlsplit

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CLOSING_BRACKETS = {")": "(", "]": "[", "}": "{"}


def _trim_url(raw: str) -> str:
    # Count once and move an end index, rather than repeatedly rescanning and
    # copying a long URL with many trailing citation delimiters.
    excess = {
        closing: raw.count(closing) - raw.count(opening)
        for closing, opening in _CLOSING_BRACKETS.items()
    }
    end = len(raw)
    while end:
        char = raw[end - 1]
        if char in ".,;:!?":
            end -= 1
        elif excess.get(char, 0) > 0:
            excess[char] -= 1
            end -= 1
        else:
            break
    return raw[:end]


def link_note_urls(blocks: list[dict]) -> list[dict]:
    """Link HTTP(S) URLs in new blocks, preserving existing marks and code.

    Accept expanded editor nodes. Only call on inserted/replaced blocks so
    untouched content is not rewritten. Existing link labels and destinations
    are authoritative, even when their visible text is another URL.
    """
    result = []
    for node in blocks:
        marks = node.get("marks", [])
        if node.get("type") == "codeBlock" or any(
            mark["type"] in ("code", "link") for mark in marks
        ):
            result.append(node)
        elif node.get("type") == "text":
            result.extend(_link_text(node))
        elif "content" in node:
            result.append({**node, "content": link_note_urls(node["content"])})
        else:
            result.append(node)
    return result


def _link_text(node: dict) -> list[dict]:
    text = node["text"]
    result = []
    cursor = 0
    previous_match_end = 0
    for match in _URL.finditer(text):
        label_boundary = previous_match_end
        previous_match_end = match.end()
        url = _trim_url(match.group())
        try:
            if not urlsplit(url).hostname:
                continue
        except ValueError:
            continue
        start, end = match.start(), match.start() + len(url)
        label = url
        if text.endswith("](", label_boundary, start) and text[end : end + 1] == ")":
            # Search only the gap since the preceding URL, even if that URL
            # was invalid. This avoids repeatedly scanning a growing prefix.
            opening = text.rfind("[", label_boundary, start - 2)
            if opening >= 0:
                candidate = text[opening + 1 : start - 2]
                if candidate and "]" not in candidate and "\n" not in candidate:
                    start = opening
                    end += 1
                    label = candidate
        if start > cursor:
            result.append({**node, "text": text[cursor:start]})
        result.append(
            {
                **node,
                "text": label,
                "marks": [
                    *node.get("marks", []),
                    {"type": "link", "attrs": {"href": url}},
                ],
            }
        )
        cursor = end
    if cursor < len(text):
        result.append({**node, "text": text[cursor:]})
    return result
