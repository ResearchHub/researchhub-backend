"""Note content versioning for programmatic writers (e.g. agent tools).

Mirrors the persistence model of ``NoteContentViewSet.create``: note content
is append-only. Every edit creates a new ``NoteContent`` row and the
``update_latest_version`` post_save signal repoints ``note.latest_version``,
so prior versions remain available as history.
"""

from note.related_models.note_model import Note, NoteContent
from researchhub_document.related_models.constants.document_type import (
    REGISTERED_REPORT,
)


def extract_plain_text(doc) -> str:
    """Concatenated text of a Tiptap/ProseMirror document.

    Top-level blocks are joined with newlines; malformed input yields ``""``.
    """
    if not isinstance(doc, dict):
        return ""
    blocks = (_node_text(child) for child in doc.get("content") or [])
    return "\n".join(block for block in blocks if block).strip()


def _node_text(node) -> str:
    if isinstance(node, dict):
        if node.get("type") == "text":
            text = node.get("text")
            return text if isinstance(text, str) else ""
        return _node_text(node.get("content"))
    if isinstance(node, list):
        return "".join(_node_text(child) for child in node)
    return ""


class NoteContentService:
    def create_version(
        self, note: Note, content_json: dict, plain_text: str | None = None
    ) -> NoteContent:
        """Append a new content version to ``note`` and return it.

        ``content_json`` must be a complete Tiptap document (``{"type": "doc",
        ...}``). ``plain_text`` is derived from the document when not given.
        Raises ``ValueError`` on invalid content or when the note backs a
        published registered report (same rule the HTTP layer enforces).
        """
        if not isinstance(content_json, dict) or content_json.get("type") != "doc":
            raise ValueError(
                "content must be a complete Tiptap document object "
                '({"type": "doc", "content": [...]})'
            )

        post = getattr(note, "post", None)
        if post is not None and post.document_type == REGISTERED_REPORT:
            raise ValueError("Published registered report content cannot be edited.")

        if plain_text is None:
            plain_text = extract_plain_text(content_json)
        return NoteContent.objects.create(
            note=note, json=content_json, plain_text=plain_text
        )
