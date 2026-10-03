from note.models import Note, NoteContent
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import NOTE
from utils.prosemirror import EDITOR_ID_ATTRS, is_trailing_paragraph


def create_note(
    created_by,
    organization,
    title="Some random post title",
    body="some text",
):
    unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=NOTE)

    note = Note.objects.create(
        created_by=created_by,
        organization=organization,
        title=title,
        unified_document=unified_doc,
    )

    note_content = NoteContent.objects.create(
        note=note,
        plain_text=body,
    )

    return (note, note_content)


def without_editor_shape(doc: dict) -> dict:
    """``doc`` minus the ids and trailing paragraph ``normalize_block_document``
    adds, for comparing stored documents against their input."""

    def strip(node):
        if not isinstance(node, dict):
            return node
        node = dict(node)
        attrs = {
            name: value
            for name, value in (node.get("attrs") or {}).items()
            if name not in EDITOR_ID_ATTRS
        }
        if attrs:
            node["attrs"] = attrs
        else:
            node.pop("attrs", None)
        if isinstance(node.get("content"), list):
            node["content"] = [strip(child) for child in node["content"]]
        return node

    stripped = strip(doc)
    content = stripped.get("content") or []
    if content and is_trailing_paragraph(content[-1]):
        stripped["content"] = content[:-1]
    return stripped
