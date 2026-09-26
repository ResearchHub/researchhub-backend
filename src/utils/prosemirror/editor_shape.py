"""Block-editor load-time normalization, done server-side.

The notebook editor (ResearchHub/web ``components/Editor/extensions``) runs
plugins that rewrite a document as soon as it loads: UniqueID stamps a uuid
``id`` on every paragraph/heading/codeBlock/table missing one, the table of
contents gives each non-empty heading a ``data-toc-id`` (and the same
``id``), and TrailingNode appends an empty paragraph unless the document
already ends in one. Any of those rewrites is a document change the editor
autosaves as a new version. ``normalize_block_document`` applies the same
rules to backend-written documents so loading them changes nothing.
"""

import uuid
from collections.abc import Callable

__all__ = [
    "EDITOR_ID_ATTRS",
    "is_trailing_paragraph",
    "normalize_block_document",
]

# UniqueID's configured types; blockquote is not in the block-editor schema.
_UNIQUE_ID_TYPES = frozenset({"paragraph", "heading", "codeBlock", "table"})
_TOC_ANCHOR_TYPES = frozenset({"heading"})
_ID = "id"
_TOC_ID = "data-toc-id"

# Editor-generated attrs: volatile identifiers, not content.
EDITOR_ID_ATTRS = frozenset({_ID, _TOC_ID})


def normalize_block_document(
    doc: dict, *, generate_id: Callable[[], str] | None = None
) -> dict:
    """A copy of ``doc`` with the ids and trailing paragraph the editor adds.

    Existing unique ids are kept; missing or duplicate ones are replaced.
    """
    generate_id = generate_id or (lambda: str(uuid.uuid4()))
    ids: set[str] = set()
    toc_ids: set[str] = set()

    def visit(node):
        if not isinstance(node, dict):
            return node
        node = dict(node)
        node_type = node.get("type")
        if node_type in _UNIQUE_ID_TYPES or node_type in _TOC_ANCHOR_TYPES:
            attrs = dict(node.get("attrs") or {})
            if node_type in _TOC_ANCHOR_TYPES and _text(node):
                toc_id = attrs.get(_TOC_ID)
                if toc_id is None or toc_id in toc_ids:
                    # The TOC plugin sets both attrs to one fresh value.
                    toc_id = generate_id()
                    attrs[_ID] = toc_id
                    attrs[_TOC_ID] = toc_id
                toc_ids.add(toc_id)
            if node_type in _UNIQUE_ID_TYPES:
                node_id = attrs.get(_ID)
                if node_id is None or node_id in ids:
                    node_id = generate_id()
                    attrs[_ID] = node_id
                ids.add(node_id)
            node["attrs"] = attrs
        content = node.get("content")
        if isinstance(content, list):
            node["content"] = [visit(child) for child in content]
        return node

    normalized = visit(doc)
    content = normalized.get("content")
    content = list(content) if isinstance(content, list) else []
    last = content[-1] if content else None
    if not isinstance(last, dict) or last.get("type") != "paragraph":
        content.append(visit({"type": "paragraph"}))
    normalized["content"] = content
    return normalized


def is_trailing_paragraph(node) -> bool:
    """Whether ``node`` is an empty paragraph like the one TrailingNode adds."""
    if not isinstance(node, dict) or node.get("type") != "paragraph":
        return False
    if node.get("content") or node.get("marks"):
        return False
    attrs = node.get("attrs") or {}
    return all(value is None for name, value in attrs.items() if name != _ID)


def _text(node) -> str:
    if isinstance(node, list):
        return "".join(_text(child) for child in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        text = node.get("text")
        return text if isinstance(text, str) else ""
    return _text(node.get("content"))
