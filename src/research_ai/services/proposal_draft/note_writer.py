"""Persist an accepted proposal as a ``Note``."""

import json

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from note.models import Note, NoteContent
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import NOTE


@transaction.atomic
def write_proposal_note(submitted: dict, *, created_by=None) -> Note:
    """Create the Note directly (headless: no notifications).

    The view paths require an auth user + org and fire org-scoped websocket
    notifications, so we create the rows directly. When ``created_by`` is
    given (the user who triggered the draft), the note lands privately in
    their notebook: owned by them, in their personal org, with user-admin /
    org-no-access permissions. For system/automatic runs it stays ownerless.
    The ``NoteContent`` post_save signal sets ``note.latest_version``.
    """
    sections = submitted.get("sections") or {}
    title = str(sections.get("title") or "").strip() or "Untitled proposal"
    unified_document = ResearchhubUnifiedDocument.objects.create(document_type=NOTE)
    note = Note.objects.create(
        created_by=created_by,
        organization=created_by.organization if created_by else None,
        title=title,
        unified_document=unified_document,
    )
    if created_by is not None:
        _create_private_permissions(created_by, unified_document)
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


def _create_private_permissions(user, unified_document) -> None:
    """Grant the user private admin access to the note document."""
    content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
    Permission.objects.create(
        access_type=ADMIN,
        content_type=content_type,
        object_id=unified_document.id,
        user=user,
    )
    Permission.objects.create(
        access_type=NO_ACCESS,
        content_type=content_type,
        object_id=unified_document.id,
        organization=user.organization,
        user=user,
    )
