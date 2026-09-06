"""Persist an accepted proposal as a ``Note``."""

import json

from django.db import transaction

from note.models import Note, NoteContent
from note.services.note_creation_service import NoteCreationService
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)


@transaction.atomic
def write_proposal_note(
    submitted: dict, *, created_by=None, selected_grant=None
) -> Note:
    """Create the Note directly (headless: no notifications).

    When ``created_by`` is given (the user who triggered the draft), the note
    lands privately in their notebook; for system/automatic runs it stays
    ownerless. The ``NoteContent`` post_save signal sets ``note.latest_version``.

    The note is a PREREGISTRATION carrying ``selected_grant`` -- the RFP the
    whole draft was written against. Both are what the notebook reads to treat
    it as a funding proposal for that grant, and a draft that arrived with its
    RFP already unset would have the user re-pick the one it answers.
    """
    sections = submitted.get("sections") or {}
    title = str(sections.get("title") or "").strip() or "Untitled proposal"
    note = NoteCreationService().create_private_note(
        created_by=created_by,
        title=title,
        document_type=PREREGISTRATION,
        selected_grant=selected_grant,
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
        created_by=created_by,
        created_via=NoteContent.CREATED_VIA_SYSTEM,
    )
    note.refresh_from_db()
    return note
