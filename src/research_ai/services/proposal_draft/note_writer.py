"""Persist an accepted proposal as a ``Note``."""

import json

from django.db import transaction

from note.models import Note, NoteContent
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import NOTE


@transaction.atomic
def write_proposal_note(submitted: dict) -> Note:
    """Create the Note directly (headless: no owner/org, no notifications).

    The view paths require an auth user + org and fire org-scoped websocket
    notifications that would dereference a null org, so we create the rows
    directly. The ``NoteContent`` post_save signal sets ``note.latest_version``.
    """
    sections = submitted.get("sections") or {}
    title = str(sections.get("title") or "").strip() or "Untitled proposal"
    unified_document = ResearchhubUnifiedDocument.objects.create(document_type=NOTE)
    note = Note.objects.create(
        created_by=None,
        organization=None,
        title=title,
        unified_document=unified_document,
    )
    prosemirror = submitted.get("prosemirror")
    NoteContent.objects.create(
        note=note,
        # Store the ProseMirror doc as a JSON-encoded string, matching the
        # shape the view path persists (the frontend POSTs ``full_json`` as a
        # string) and the editor's ``JSON.parse(contentJson)`` expects. A raw
        # object round-trips as an object and breaks note loading.
        json=json.dumps(prosemirror) if prosemirror is not None else None,
        plain_text=str(submitted.get("plain_text") or ""),
    )
    note.refresh_from_db()
    return note
