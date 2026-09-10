"""Make source URLs clickable in blocks written by note agents."""

import re
from urllib.parse import urlsplit

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_MARKDOWN_START = re.compile(r"\[([^\[\]\n]+)\]\((https?://)", re.IGNORECASE)
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


def _is_web_url(url: str) -> bool:
    try:
        return bool(urlsplit(url).hostname)
    except ValueError:
        return False


def _destination_end(text: str, start: int) -> tuple[int, bool]:
    """Read a Markdown destination, keeping balanced URL parentheses.

    Return the scan endpoint even on failure so callers never rescan a long
    malformed destination for every apparent link nested inside it.
    """
    depth = 1
    for index in range(start, len(text)):
        char = text[index]
        if char.isspace() or char in "<>\"'":
            return index + 1, False
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1, True
    return len(text), False


def _markdown_links(text: str):
    """Yield complete Markdown links before considering bare URLs."""
    cursor = 0
    while match := _MARKDOWN_START.search(text, cursor):
        start = match.start(2)
        cursor, complete = _destination_end(text, start)
        url = text[start : cursor - 1]
        if complete and _is_web_url(url):
            yield match.start(), cursor, match.group(1), url


def _linked_node(node: dict, label: str, url: str) -> dict:
    return {
        **node,
        "text": label,
        "marks": [
            *node.get("marks", []),
            {"type": "link", "attrs": {"href": url}},
        ],
    }


def _link_bare_urls(node: dict, text: str) -> list[dict]:
    result = []
    cursor = 0
    for match in _URL.finditer(text):
        url = _trim_url(match.group())
        if not _is_web_url(url):
            continue
        if match.start() > cursor:
            result.append({**node, "text": text[cursor : match.start()]})
        result.append(_linked_node(node, url, url))
        cursor = match.start() + len(url)
    if cursor < len(text):
        result.append({**node, "text": text[cursor:]})
    return result


def _link_text(node: dict) -> list[dict]:
    text = node["text"]
    result = []
    cursor = 0
    for start, end, label, url in _markdown_links(text):
        result.extend(_link_bare_urls(node, text[cursor:start]))
        result.append(_linked_node(node, label, url))
        cursor = end
    result.extend(_link_bare_urls(node, text[cursor:]))
    return result
