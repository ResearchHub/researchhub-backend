"""Permission-checked, conflict-safe writes for note content."""

import json

from django.db import transaction

from note.models import Note, NoteContent
from note.services.note_blocks import derive_plain_text
from researchhub_document.related_models.constants.document_type import (
    REGISTERED_REPORT,
)


class NoteEditDenied(Exception):  # noqa: N818 - public contract uses this name
    """The acting user cannot edit the note."""


class NoteEditBlocked(Exception):  # noqa: N818 - public contract uses this name
    """The note is immutable because it is a published registered report."""


class NoteVersionConflict(Exception):  # noqa: N818 - public contract uses this name
    """The supplied version token is not the note's current version."""

    def __init__(self, current_version_id: int | None):
        self.current_version_id = current_version_id
        super().__init__(f"Note changed; current version is {current_version_id}.")


class NoteContentService:
    """Write note-domain state after re-checking current permissions."""

    @staticmethod
    def _ensure_can_edit(note: Note, user) -> None:
        if not getattr(user, "is_authenticated", False):
            raise NoteEditDenied("You do not have permission to edit this note.")

        permissions = note.unified_document.permissions
        if not (permissions.has_admin_user(user) or permissions.has_editor_user(user)):
            raise NoteEditDenied("You do not have permission to edit this note.")

    @staticmethod
    def _ensure_not_published_registered_report(note: Note) -> None:
        post = getattr(note, "post", None)
        if post is not None and post.document_type == REGISTERED_REPORT:
            raise NoteEditBlocked(
                "Published registered report content cannot be edited."
            )

    @transaction.atomic
    def save_version(
        self,
        note: Note,
        doc: dict,
        *,
        user,
        expected_version_id: int | None,
    ) -> NoteContent:
        """Append a content version while holding the note's write lock."""
        locked_note = (
            Note.objects.select_for_update()
            .select_related("unified_document")
            .get(pk=note.pk)
        )
        self._ensure_can_edit(locked_note, user)
        self._ensure_not_published_registered_report(locked_note)

        if (
            expected_version_id is not None
            and locked_note.latest_version_id != expected_version_id
        ):
            raise NoteVersionConflict(locked_note.latest_version_id)

        return NoteContent.objects.create(
            note=locked_note,
            json=json.dumps(doc),
            plain_text=derive_plain_text(doc),
        )

    def set_title(self, note: Note, title: str, *, user) -> Note:
        """Update a title under lock, then notify the organization room."""
        with transaction.atomic():
            locked_note = (
                Note.objects.select_for_update()
                .select_related("unified_document")
                .get(pk=note.pk)
            )
            self._ensure_can_edit(locked_note, user)
            locked_note.title = title
            locked_note.save(update_fields=["title", "updated_date"])

        locked_note.notify_note_updated_title()
        return locked_note
