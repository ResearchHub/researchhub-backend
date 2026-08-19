"""Loader for the vendored ProseMirror schemas; see the package docstring."""

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path

from prosemirror.model import Node, Schema

# Notebook notes and posts (web: components/Editor).
BLOCK_EDITOR = "block-editor"
# Comments, including review mode (web: components/Comment).
COMMENT_EDITOR = "comment-editor"

_SCHEMA_DIR = Path(__file__).parent / "schemas"


@cache
def get_schema(name: str) -> Schema:
    """Return the exported ProseMirror schema ``name`` (cached per process)."""
    with open(_SCHEMA_DIR / f"{name}.json") as f:
        return Schema(json.load(f))


def parse_document(schema_name: str, doc: dict) -> Node:
    """Parse and validate a TipTap/ProseMirror document in JSON form.

    Returns the parsed ``Node`` with attribute defaults filled in. Raises
    ``ValueError`` if the document JSON is structurally malformed, if the
    root is not the schema's top-level ``doc`` node, if the document
    references unknown node/mark types, JSON keys, or attributes, omits a
    required attribute, or violates the schema's nesting rules.
    """
    schema = get_schema(schema_name)
    try:
        node = Node.from_json(schema, doc)
        _reject_unknown_keys(schema, doc)
    except (AttributeError, KeyError, TypeError) as e:
        # prosemirror-py leaks these for malformed shapes (a node missing
        # "type", non-dict nodes or attrs); keep the ValueError contract.
        raise ValueError(f"malformed document JSON: {e!r}") from e
    if node.type is not schema.top_node_type:
        raise ValueError(
            f"expected top-level {schema.top_node_type.name!r} node,"
            f" got {node.type.name!r}"
        )
    node.check()
    return node


# The JSON object keys Node.from_json() reads for each node kind.
_NODE_KEYS = frozenset(("type", "attrs", "content", "marks"))
_TEXT_NODE_KEYS = frozenset(("type", "text", "marks"))
_MARK_KEYS = frozenset(("type", "attrs"))


def _reject_unknown_keys(schema: Schema, node_json: dict) -> None:
    # Node.from_json() ignores JSON keys and attribute names it doesn't
    # recognize ("contents", "usrId"), so a misspelling would otherwise pass
    # validation and silently drop the data under it.
    node_type = schema.nodes[node_json["type"]]
    node_keys = _TEXT_NODE_KEYS if node_type.is_text else _NODE_KEYS
    _reject_unknown(node_json, node_keys, f"keys on node {node_type.name!r}")
    _reject_unknown(
        node_json.get("attrs"),
        node_type.attrs,
        f"attributes on node {node_type.name!r}",
    )
    for mark_json in node_json.get("marks") or ():
        mark_type = schema.marks[mark_json["type"]]
        _reject_unknown(mark_json, _MARK_KEYS, f"keys on mark {mark_type.name!r}")
        _reject_unknown(
            mark_json.get("attrs"),
            mark_type.attrs,
            f"attributes on mark {mark_type.name!r}",
        )
    for child in node_json.get("content") or ():
        _reject_unknown_keys(schema, child)


def _reject_unknown(found: dict | None, allowed: Iterable[str], what: str) -> None:
    unknown = set(found or ()) - set(allowed)
    if unknown:
        raise ValueError(f"unknown {what}: " + ", ".join(sorted(unknown)))
