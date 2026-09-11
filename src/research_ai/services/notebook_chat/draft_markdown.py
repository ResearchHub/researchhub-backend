"""Bounded, presentation-only Markdown from incomplete note tool arguments."""

import re
from urllib.parse import quote, urlsplit

import jiter

MAX_INPUT_BYTES = 128_000
MAX_MARKDOWN_CHARS = 20_000


def _escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", text)


def _children(node: dict) -> list:
    content = node.get("content")
    return content if isinstance(content, list) else []


def _render(node, depth=0, inline=False) -> str:
    if depth > 24:
        return ""
    if isinstance(node, str):
        return _escape(node)
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    children = _children(node)
    attrs = node.get("attrs")
    attrs = attrs if isinstance(attrs, dict) else {}
    if kind == "text":
        value = node.get("text")
        text = _escape(value) if isinstance(value, str) else ""
        marks = node.get("marks")
        for mark in marks if isinstance(marks, list) else []:
            if not isinstance(mark, dict):
                continue
            mark_type = mark.get("type")
            delimiter = {"bold": "**", "italic": "*", "strike": "~~"}.get(mark_type)
            if delimiter and text:
                text = f"{delimiter}{text}{delimiter}"
            elif mark_type == "link":
                mark_attrs = mark.get("attrs")
                href = mark_attrs.get("href") if isinstance(mark_attrs, dict) else None
                if isinstance(href, str) and urlsplit(href).scheme in {
                    "http",
                    "https",
                    "mailto",
                }:
                    text = f"[{text}]({quote(href, safe=':/?=&%#@+;')})"
        return text
    if kind == "hardBreak":
        return "\n"
    if kind == "horizontalRule":
        return "---"
    if kind in {"paragraph", "heading"}:
        text = "".join(_render(child, depth + 1, inline=True) for child in children)
        if kind == "heading" and text:
            level = attrs.get("level", 2)
            level = min(6, max(1, level)) if isinstance(level, int) else 2
            return f"{'#' * level} {text}"
        return text
    if kind in {"bulletList", "orderedList", "taskList"}:
        lines = []
        start = attrs.get("start", 1)
        start = start if isinstance(start, int) else 1
        for index, child in enumerate(children):
            text = _render(child, depth + 1)
            if not text:
                continue
            prefix = f"{start + index}. " if kind == "orderedList" else "- "
            lines.append(prefix + text.replace("\n", "\n" + " " * len(prefix)))
        return "\n".join(lines)
    if kind == "blockquote":
        text = "\n\n".join(_render(child, depth + 1) for child in children)
        return "\n".join("> " + line for line in text.splitlines())
    # Unknown/incomplete node types can surface their text, but no ids,
    # attributes, tool arguments or raw HTML become presentation content.
    separator = "" if inline else "\n\n"
    return separator.join(
        filter(None, (_render(child, depth + 1) for child in children))
    )


class ToolDraftMarkdown:
    """Accumulate bounded JSON; format only note blocks at stream flush time.

    jiter's partial mode includes unfinished text strings and handles split
    escapes. The snapshot can replace itself as later attrs/marks arrive,
    independent of JSON key order. It never writes to the note or its version.
    """

    def __init__(self):
        self._input = bytearray()
        self._last = ""

    def feed(self, fragment: str) -> None:
        room = MAX_INPUT_BYTES - len(self._input)
        if room > 0:
            self._input.extend(fragment.encode("utf-8")[:room])

    def snapshot(self) -> str:
        try:
            payload = jiter.from_json(
                bytes(self._input), partial_mode="trailing-strings"
            )
            edits = payload.get("edits", []) if isinstance(payload, dict) else []
            blocks = []
            for edit in edits if isinstance(edits, list) else []:
                if isinstance(edit, dict) and isinstance(edit.get("blocks"), list):
                    blocks.extend(edit["blocks"])
            self._last = "\n\n".join(
                filter(None, (_render(block) for block in blocks))
            )[:MAX_MARKDOWN_CHARS]
        except (ValueError, TypeError, RecursionError):
            pass
        return self._last
