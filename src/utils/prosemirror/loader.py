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

    Returns the parsed ``Node`` with attribute defaults filled in and any
    unrecognized attributes silently stripped (prosemirror-py ignores them
    rather than rejecting). Raises ``ValueError`` if the document references
    unknown node/mark types, omits a required attribute, or violates the
    schema's nesting rules.
    """
    node = Node.from_json(get_schema(schema_name), doc)
    node.check()
    return node
