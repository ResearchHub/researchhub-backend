from note.models import Note, NoteContent
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.models.constants.document_type import NOTE


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
