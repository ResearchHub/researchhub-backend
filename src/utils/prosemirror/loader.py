"""Loader for the vendored ProseMirror schemas; see the package docstring."""

import json
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
    ``ValueError`` if the root is not the schema's top-level ``doc`` node, if
    the document references unknown node/mark types or attributes, omits a
    required attribute, or violates the schema's nesting rules.
    """
    schema = get_schema(schema_name)
    node = Node.from_json(schema, doc)
    if node.type is not schema.top_node_type:
        raise ValueError(
            f"expected top-level {schema.top_node_type.name!r} node,"
            f" got {node.type.name!r}"
        )
    _reject_unknown_attrs(schema, doc)
    node.check()
    return node


def _reject_unknown_attrs(schema: Schema, node_json: dict) -> None:
    # Node.from_json() drops attribute keys the schema doesn't declare, so a
    # misspelled key would otherwise pass validation and lose its data.
    unknown = set(node_json.get("attrs") or ()) - set(
        schema.nodes[node_json["type"]].attrs
    )
    if unknown:
        raise ValueError(
            f"unknown attributes on node {node_json['type']!r}: "
            + ", ".join(sorted(unknown))
        )
    for mark_json in node_json.get("marks") or ():
        unknown = set(mark_json.get("attrs") or ()) - set(
            schema.marks[mark_json["type"]].attrs
        )
        if unknown:
            raise ValueError(
                f"unknown attributes on mark {mark_json['type']!r}: "
                + ", ".join(sorted(unknown))
            )
    for child in node_json.get("content") or ():
        _reject_unknown_attrs(schema, child)
