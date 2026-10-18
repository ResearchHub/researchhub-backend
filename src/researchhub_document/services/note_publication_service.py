from rest_framework.exceptions import PermissionDenied, ValidationError

from note.models import Note
from researchhub_document.models import ResearchhubPost
from user.models import User


class NotePublicationService:
    def get_note_for_publication(self, note_id: int, user: User) -> Note:
        """Lock and validate a draft inside the caller's publication transaction."""
        if user is None or not user.is_authenticated:
            raise PermissionDenied("Authentication is required to publish a note.")

        try:
            note = (
                Note.objects.select_for_update()
                .select_related("unified_document")
                .get(id=note_id, unified_document__is_removed=False)
            )
        except (Note.DoesNotExist, TypeError, ValueError) as error:
            raise ValidationError({"note_id": "Note not found."}) from error

        permissions = note.permissions
        if not (
            note.created_by_id == user.id
            or permissions.has_admin_user(user)
            or permissions.has_editor_user(user)
        ):
            raise PermissionDenied("You do not have permission to publish this note.")

        if ResearchhubPost.objects.filter(note_id=note.pk).exists():
            raise ValidationError({"note_id": "This note has already been published."})

        return note
