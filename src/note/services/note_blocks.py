"""Convert between bounded note blocks and ProseMirror documents.

This module is the note domain's ProseMirror boundary. The block model uses a
small inline grammar (links, code, bold, and italic) and deliberately has no
escaping syntax in v1. Unmatched or malformed delimiters remain literal text.
"""

import re
from dataclasses import dataclass


class NoteBlockError(ValueError):
    """Structured block input cannot be converted to a note document."""


@dataclass(frozen=True, slots=True)
class RenderedBlock:
    """A model-facing rendering of one top-level ProseMirror block."""

    index: int
    type: str
    content: str
    supported: bool
    level: int | None = None


_INLINE_PATTERN = re.compile(
    r"\[(?P<link_text>[^\]\n]+)\]\((?P<link_href>[^)\n]+)\)"
    r"|`(?P<code>[^`\n]+)`"
    r"|\*\*\*(?P<bold_italic>[^*\n]+)\*\*\*"
    r"|\*\*(?P<bold>[^*\n]+(?:\*(?!\*)[^*\n]+)*)\*\*"
    r"|(?<!\*)\*(?P<italic>[^*\n]+)\*(?!\*)"
)


def _mark(mark_type: str, **attrs) -> dict:
    mark = {"type": mark_type}
    if attrs:
        mark["attrs"] = attrs
    return mark


def _append_text(nodes: list[dict], text: str, marks: list[dict] | None = None) -> None:
    if not text:
        return

    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks

    if nodes and nodes[-1].get("marks") == node.get("marks"):
        nodes[-1]["text"] += text
    else:
        nodes.append(node)


def _add_mark(nodes: list[dict], mark: dict) -> list[dict]:
    marked = []
    for node in nodes:
        copy = dict(node)
        copy["marks"] = [*copy.get("marks", []), mark]
        marked.append(copy)
    return marked


def parse_inline(text: str) -> list[dict]:
    """Parse the v1 inline grammar into ProseMirror text nodes.

    Complete constructs are recognized left-to-right with links, code, bold,
    and italic as the precedence order. There is intentionally no escaping in
    v1. Malformed constructs are emitted as literal text and never raise.
    """
    if not isinstance(text, str):
        text = str(text)

    nodes: list[dict] = []
    cursor = 0
    for match in _INLINE_PATTERN.finditer(text):
        _append_text(nodes, text[cursor : match.start()])

        if match.group("link_text") is not None:
            inner = parse_inline(match.group("link_text"))
            parsed = _add_mark(inner, _mark("link", href=match.group("link_href")))
        elif match.group("code") is not None:
            parsed = []
            _append_text(parsed, match.group("code"), [_mark("code")])
        elif match.group("bold_italic") is not None:
            inner = parse_inline(match.group("bold_italic"))
            parsed = _add_mark(_add_mark(inner, _mark("italic")), _mark("bold"))
        elif match.group("bold") is not None:
            parsed = _add_mark(parse_inline(match.group("bold")), _mark("bold"))
        else:
            parsed = _add_mark(parse_inline(match.group("italic")), _mark("italic"))

        for node in parsed:
            _append_text(nodes, node["text"], node.get("marks"))
        cursor = match.end()

    _append_text(nodes, text[cursor:])
    return nodes


def render_inline(nodes: object) -> str:
    """Render ProseMirror inline nodes using the v1 inline grammar."""
    if not isinstance(nodes, list):
        return ""

    rendered: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "text":
            rendered.append(render_inline(node.get("content")))
            continue

        text = str(node.get("text", ""))
        marks = node.get("marks")
        marks = marks if isinstance(marks, list) else []
        mark_types = {
            mark.get("type")
            for mark in marks
            if isinstance(mark, dict) and isinstance(mark.get("type"), str)
        }

        if "code" in mark_types:
            text = f"`{text}`"
        if "italic" in mark_types:
            text = f"*{text}*"
        if "bold" in mark_types:
            text = f"**{text}**"

        link = next(
            (
                mark
                for mark in marks
                if isinstance(mark, dict) and mark.get("type") == "link"
            ),
            None,
        )
        if link is not None:
            attrs = link.get("attrs")
            href = attrs.get("href") if isinstance(attrs, dict) else None
            if isinstance(href, str) and href:
                text = f"[{text}]({href})"

        rendered.append(text)

    return "".join(rendered)


def _extract_text(node: object) -> str:
    if not isinstance(node, dict):
        return ""
    own_text = node.get("text") if node.get("type") == "text" else ""
    own_text = own_text if isinstance(own_text, str) else ""
    content = node.get("content")
    if not isinstance(content, list):
        return own_text
    return own_text + "".join(_extract_text(child) for child in content)


def _render_list_item(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    content = item.get("content")
    if not isinstance(content, list):
        return ""

    parts = []
    for child in content:
        if not isinstance(child, dict):
            continue
        child_content = child.get("content")
        rendered = render_inline(child_content)
        if not rendered:
            rendered = _extract_text(child)
        if rendered:
            parts.append(rendered)
    return " ".join(parts)


def render_blocks(doc: dict) -> list[RenderedBlock]:
    """Render the top-level blocks of a ProseMirror document."""
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise NoteBlockError("Note content must be a ProseMirror document.")
    content = doc.get("content", [])
    if not isinstance(content, list):
        raise NoteBlockError("The note document's content must be a list.")

    rendered = []
    for index, node in enumerate(content):
        if not isinstance(node, dict):
            rendered.append(RenderedBlock(index, "unknown", "[unknown]", False))
            continue

        node_type = node.get("type")
        if node_type == "heading":
            attrs = node.get("attrs")
            level = attrs.get("level") if isinstance(attrs, dict) else None
            level = (
                level if isinstance(level, int) and not isinstance(level, bool) else 1
            )
            rendered.append(
                RenderedBlock(
                    index,
                    "heading",
                    render_inline(node.get("content")),
                    True,
                    level,
                )
            )
        elif node_type == "paragraph":
            rendered.append(
                RenderedBlock(
                    index,
                    "paragraph",
                    render_inline(node.get("content")),
                    True,
                )
            )
        elif node_type in {"bulletList", "orderedList"}:
            items = node.get("content")
            items = items if isinstance(items, list) else []
            item_text = [_render_list_item(item) for item in items]
            ordered = node_type == "orderedList"
            lines = [
                f"{item_index + 1}. {text}" if ordered else f"- {text}"
                for item_index, text in enumerate(item_text)
            ]
            rendered.append(
                RenderedBlock(
                    index,
                    "ordered_list" if ordered else "bullet_list",
                    "\n".join(lines),
                    True,
                )
            )
        else:
            placeholder = f"[{node_type or 'unknown'}]"
            extracted = _extract_text(node)
            if extracted:
                placeholder = f"{placeholder} {extracted}"
            rendered.append(
                RenderedBlock(
                    index,
                    str(node_type or "unknown"),
                    placeholder,
                    False,
                )
            )

    return rendered


def _require_text(block: dict, index: int) -> str:
    if "text" not in block:
        raise NoteBlockError(f"Block {index} must include a text string.")
    text = block["text"]
    if not isinstance(text, str):
        raise NoteBlockError(f"Block {index} text must be a string.")
    return text


def _text_block(node_type: str, text: str, attrs: dict | None = None) -> dict:
    node = {"type": node_type}
    if attrs is not None:
        node["attrs"] = attrs
    content = parse_inline(text)
    if content:
        node["content"] = content
    return node


def build_nodes(blocks: list[dict]) -> list[dict]:
    """Build ProseMirror top-level nodes from structured note blocks."""
    if not isinstance(blocks, list):
        raise NoteBlockError("Blocks must be provided as a list.")

    nodes = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise NoteBlockError(f"Block {index} must be an object.")

        block_type = block.get("type")
        if block_type == "heading":
            level = block.get("level")
            if (
                not isinstance(level, int)
                or isinstance(level, bool)
                or not 1 <= level <= 6
            ):
                raise NoteBlockError(
                    f"Block {index} heading level must be an integer from 1 to 6."
                )
            nodes.append(
                _text_block(
                    "heading",
                    _require_text(block, index),
                    {"level": level},
                )
            )
        elif block_type == "paragraph":
            nodes.append(_text_block("paragraph", _require_text(block, index)))
        elif block_type in {"bullet_list", "ordered_list"}:
            items = block.get("items")
            if not isinstance(items, list) or not all(
                isinstance(item, str) for item in items
            ):
                raise NoteBlockError(f"Block {index} items must be a list of strings.")
            list_items = [
                {
                    "type": "listItem",
                    "content": [_text_block("paragraph", item)],
                }
                for item in items
            ]
            nodes.append(
                {
                    "type": (
                        "bulletList" if block_type == "bullet_list" else "orderedList"
                    ),
                    "content": list_items,
                }
            )
        else:
            raise NoteBlockError(
                f"Block {index} has unsupported type {block_type!r}. "
                "Use heading, paragraph, bullet_list, or ordered_list."
            )

    return nodes


def derive_plain_text(doc: dict) -> str:
    """Derive plain text from every top-level block in a document."""
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise NoteBlockError("Note content must be a ProseMirror document.")
    content = doc.get("content", [])
    if not isinstance(content, list):
        raise NoteBlockError("The note document's content must be a list.")
    return "\n\n".join(_extract_text(block) for block in content)
