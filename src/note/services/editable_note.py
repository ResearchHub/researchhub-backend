"""Eligibility checks for notes edited by the notebook AI assistant.

The frontend Tiptap editor owns full ProseMirror schema validation. This module
only enforces the root invariant that distinguishes a current editable note
from legacy/read-only note content before the backend persists an AI edit.
"""


class UnsupportedEditableNoteError(ValueError):
    """The document does not use the editable-note root schema."""


def require_editable_note(doc: object) -> dict:
    """Require the editable ``heading block+`` document envelope.

    Node and mark validity is checked by the live Tiptap schema that produced
    the document. Django deliberately does not duplicate that schema.
    """
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise UnsupportedEditableNoteError(
            "Note content must be a ProseMirror document."
        )

    content = doc.get("content")
    if not isinstance(content, list) or len(content) < 2:
        raise UnsupportedEditableNoteError(
            "AI editing requires an editable note with a heading and body block."
        )

    first = content[0]
    if not isinstance(first, dict) or first.get("type") != "heading":
        raise UnsupportedEditableNoteError(
            "AI editing is only available for notes created by the editable editor."
        )

    if any(
        not isinstance(node, dict) or not isinstance(node.get("type"), str)
        for node in content
    ):
        raise UnsupportedEditableNoteError("Note content contains an invalid block.")

    return doc
