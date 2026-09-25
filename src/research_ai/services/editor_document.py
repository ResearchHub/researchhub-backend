"""Prepare agent-written ProseMirror documents for the notebook editor.

The frontend's UniqueID and TrailingNode extensions otherwise change these
documents as soon as they load, before the user makes an edit.
"""

from copy import deepcopy
from uuid import uuid4

_ID_NODE_TYPES = frozenset({"paragraph", "heading", "blockquote", "codeBlock", "table"})


def prepare_agent_document(document: dict) -> dict:
    """Return a copy with stable block IDs and the editor's trailing node."""
    prepared = deepcopy(document)
    used_ids: set[str] = set()

    def assign_ids(node: dict) -> None:
        if node.get("type") in _ID_NODE_TYPES:
            attrs = node.setdefault("attrs", {})
            node_id = attrs.get("id")
            if not isinstance(node_id, str) or not node_id or node_id in used_ids:
                node_id = str(uuid4())
                attrs["id"] = node_id
            used_ids.add(node_id)
        for child in node.get("content", ()):
            assign_ids(child)

    for block in prepared.get("content", ()):
        assign_ids(block)

    content = prepared.get("content")
    if content is not None and (not content or content[-1].get("type") != "paragraph"):
        trailing = {"type": "paragraph"}
        assign_ids(trailing)
        content.append(trailing)
    return prepared
