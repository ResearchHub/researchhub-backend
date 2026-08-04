"""Lossless bounded reads and text projection for Tiptap documents."""

import copy
import re

from note.services.document_engine.errors import InvalidDocumentOperation
from note.services.document_engine.registry import (
    CREATABLE_TOP_LEVEL_NODES,
    MAX_READ_BLOCKS,
    PREVIEW_LENGTH,
)

_WHITESPACE = re.compile(r"\s+")
_INLINE_CONTAINERS = frozenset(
    {"paragraph", "heading", "detailsSummary", "figcaption", "quoteCaption"}
)
_BLOCK_CONTAINERS = frozenset(
    {
        "doc",
        "listItem",
        "taskItem",
        "details",
        "detailsContent",
        "columns",
        "column",
        "blockquoteFigure",
        "quote",
        "figure",
    }
)


def derive_plain_text(doc: dict) -> str:
    """Derive readable text without using it to reconstruct canonical JSON."""

    return _node_text(doc)


def read_document(doc: dict, *, start: int = 0, limit: int = MAX_READ_BLOCKS) -> dict:
    """Return a bounded top-level slice with stable locators and exact JSON."""

    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        raise InvalidDocumentOperation(
            "from must be a non-negative integer", path="from"
        )
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_READ_BLOCKS
    ):
        raise InvalidDocumentOperation(
            f"limit must be an integer from 1 through {MAX_READ_BLOCKS}", path="limit"
        )

    content = doc.get("content", [])
    total = len(content)
    end = min(start + limit, total)
    selected = content[start:end] if start < total else []
    blocks = []
    for relative_index, node in enumerate(selected):
        index = start + relative_index
        node_text = _node_text(node)
        blocks.append(
            {
                "locator": block_locator(node, index),
                "index": index,
                "node": copy.deepcopy(node),
                "plain_text_preview": _preview(node_text),
                "capabilities": block_capabilities(node),
            }
        )

    has_more = end < total
    return {
        "doc": {"type": "doc", "content": copy.deepcopy(selected)},
        "blocks": blocks,
        "from": start,
        "limit": limit,
        "total": total,
        "returned": len(selected),
        "has_more": has_more,
        "next_from": end if has_more else None,
        "plain_text": _node_text({"type": "doc", "content": selected}),
    }


def block_locator(node: dict, index: int) -> str:
    node_id = node.get("attrs", {}).get("id")
    return node_id if isinstance(node_id, str) and node_id else f"i:{index}"


def block_capabilities(node: dict) -> list[str]:
    capabilities = ["insert_after", "move", "delete"]
    if node.get("type") in CREATABLE_TOP_LEVEL_NODES:
        capabilities.insert(0, "replace")
    return capabilities


def _preview(value: str) -> str:
    compact = _WHITESPACE.sub(" ", value).strip()
    if len(compact) <= PREVIEW_LENGTH:
        return compact
    return f"{compact[: PREVIEW_LENGTH - 1]}…"


def _node_text(node: dict) -> str:
    node_type = node.get("type")
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"
    if node_type == "imageBlock":
        return _string_attr(node, "alt")
    if node_type == "emoji":
        return _string_attr(node, "name")
    if node_type == "youtube":
        return _string_attr(node, "src")

    children = [_node_text(child) for child in node.get("content", [])]
    if node_type in _INLINE_CONTAINERS or node_type == "codeBlock":
        return "".join(children)
    if node_type == "tableRow":
        return "\t".join(children)
    if node_type in {"table", "bulletList", "orderedList", "taskList"}:
        return "\n".join(_nonempty_or_structural(children))
    if node_type in {"tableCell", "tableHeader"} | _BLOCK_CONTAINERS:
        return "\n".join(_nonempty_or_structural(children))

    # Unknown nodes remain lossless in JSON. Generic recursive projection still
    # exposes any ordinary text leaves they contain.
    return "\n".join(_nonempty_or_structural(children))


def _nonempty_or_structural(values: list[str]) -> list[str]:
    return [value for value in values if value != ""]


def _string_attr(node: dict, name: str) -> str:
    value = node.get("attrs", {}).get(name)
    return value if isinstance(value, str) else ""
