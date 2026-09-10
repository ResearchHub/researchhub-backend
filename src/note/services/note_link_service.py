"""Make source URLs clickable in blocks written by note agents."""

import re
from urllib.parse import urlsplit

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_MARKDOWN_LABEL = re.compile(r"\[([^\[\]\n]+)\]\($")


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
    for match in _URL.finditer(text):
        url = match.group().rstrip(".,;:!?")
        # Keep balanced parentheses in DOI URLs, excluding citation delimiters.
        while (
            url
            and url[-1] in ")]}"
            and (
                url.count(url[-1]) > url.count({")": "(", "]": "[", "}": "{"}[url[-1]])
            )
        ):
            url = url[:-1].rstrip(".,;:!?")
        try:
            if not urlsplit(url).hostname:
                continue
        except ValueError:
            continue
        start, end = match.start(), match.start() + len(url)
        label = url
        markdown = _MARKDOWN_LABEL.search(text[cursor:start])
        if markdown is not None and text[end : end + 1] == ")":
            start = cursor + markdown.start()
            end += 1
            label = markdown.group(1)
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
