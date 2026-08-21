"""Compact JSON dialect for model-facing ProseMirror documents.

Canonical TipTap/ProseMirror JSON spells out every text run as a node object
and, as the editors emit it, every attribute including schema defaults. For a
language model that reads and writes documents through tools, that costs
several times the tokens the content itself needs -- in both directions. This
module converts between canonical documents and a compact, loss-free dialect:

- attributes equal to their schema default are omitted (parsing fills them
  back in), and empty ``attrs``/``marks``/``content`` containers are dropped;
- an unmarked text node is a bare string;
- at the document's top level only, a paragraph with default attributes
  holding a single unmarked text node is a bare string, and an empty
  paragraph is ``""``.

``compact_blocks`` validates a document against a schema and returns its
top-level blocks in compact form; ``parse_blocks`` accepts blocks in the same
dialect (canonical form is a subset of it) and returns validated canonical
block dicts.
"""

from prosemirror.model import Mark, Node

from utils.prosemirror.loader import parse_document

__all__ = ["compact_blocks", "expand_blocks", "parse_blocks"]


def compact_blocks(schema_name: str, doc: dict) -> list[dict | str]:
    """Validate ``doc`` and return its top-level blocks in compact form.

    Raises ``ValueError`` (from ``parse_document``) when the document does
    not satisfy the schema.
    """
    node = parse_document(schema_name, doc)
    return [_compact_block(child) for child in node.children]


def expand_blocks(blocks: list) -> list[dict]:
    """Expand compact ``blocks`` into canonical TipTap block dicts.

    A bare string at this level becomes a paragraph; bare strings nested in
    ``content`` arrays become text nodes. No schema validation happens here;
    malformed shapes pass through for ``parse_document`` to report.
    """
    return [_expand_block(block) for block in blocks]


def parse_blocks(schema_name: str, blocks: list) -> list[dict]:
    """Expand and schema-validate compact ``blocks`` as document content.

    Returns the canonical block dicts (attribute defaults filled in) that
    the validated document serializes to. Raises ``ValueError`` when
    ``blocks`` is not a non-empty list or any block violates the schema.
    """
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("blocks must be a non-empty array of block objects")
    document = {"type": "doc", "content": expand_blocks(blocks)}
    return parse_document(schema_name, document).to_json()["content"]


# -- compaction ------------------------------------------------------------


def _compact_block(node: Node) -> dict | str:
    """A top-level block; plain default paragraphs compact to bare strings."""
    if node.type.name == "paragraph" and not node.marks:
        if _non_default_attrs(node):
            return _compact_node(node)
        if node.child_count == 0:
            return ""
        if node.child_count == 1:
            child = node.child(0)
            if child.is_text and not child.marks:
                return child.text
    return _compact_node(node)


def _compact_node(node: Node) -> dict | str:
    if node.is_text:
        if not node.marks:
            return node.text
        return {
            "type": "text",
            "text": node.text,
            "marks": [_compact_mark(mark) for mark in node.marks],
        }
    compacted: dict = {"type": node.type.name}
    attrs = _non_default_attrs(node)
    if attrs:
        compacted["attrs"] = attrs
    if node.marks:
        compacted["marks"] = [_compact_mark(mark) for mark in node.marks]
    if node.child_count:
        compacted["content"] = [_compact_node(child) for child in node.children]
    return compacted


def _compact_mark(mark: Mark) -> dict:
    compacted: dict = {"type": mark.type.name}
    attrs = _non_default_attrs(mark)
    if attrs:
        compacted["attrs"] = attrs
    return compacted


def _non_default_attrs(node_or_mark: Node | Mark) -> dict:
    specs = node_or_mark.type.attrs
    return {
        name: value
        for name, value in node_or_mark.attrs.items()
        if not _is_default(specs[name], value)
    }


def _is_default(spec, value) -> bool:
    # Type-sensitive on purpose: 1 == True in Python, but they are different
    # JSON values and refilling the default would change the document.
    return (
        spec.has_default and spec.default == value and type(spec.default) is type(value)
    )


# -- expansion ---------------------------------------------------------------


def _expand_block(block) -> dict:
    if isinstance(block, str):
        if not block:
            return {"type": "paragraph"}
        return {"type": "paragraph", "content": [{"type": "text", "text": block}]}
    return _expand_node(block)


def _expand_node(node):
    if isinstance(node, str):
        return {"type": "text", "text": node}
    if not isinstance(node, dict):
        return node
    expanded = dict(node)
    content = expanded.get("content")
    if isinstance(content, list):
        expanded["content"] = [_expand_node(child) for child in content]
    return expanded
