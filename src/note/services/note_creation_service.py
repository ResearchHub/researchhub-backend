"""Headless note creation, outside the request path.

``NoteViewSet.create`` needs a request and an organization and broadcasts an
org-wide websocket notification; agent workflows create notes with none of
that. The rows written here match the view's PRIVATE grouping: the note lands
in the creator's personal organization with user-admin / org-no-access
permissions, so only the creator (and anyone they later invite) can see it.
"""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from note.related_models.note_model import Note
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import NOTE


class NoteCreationService:
    @transaction.atomic
    def create_private_note(
        self,
        *,
        created_by,
        title: str,
        document_type: str = NOTE,
        selected_grant=None,
    ) -> Note:
        """Create a note only ``created_by`` can access; ownerless when None.

        No ``NoteContent`` is written: the note reads as empty until a first
        version is saved, which is how the agent note tools populate it.
        """
        unified_document = ResearchhubUnifiedDocument.objects.create(document_type=NOTE)
        note = Note.objects.create(
            created_by=created_by,
            document_type=document_type,
            organization=(
                getattr(created_by, "organization", None) if created_by else None
            ),
            selected_grant=selected_grant,
            title=title,
            unified_document=unified_document,
        )
        if created_by is not None:
            self._create_private_permissions(created_by, unified_document)
        return note

    @staticmethod
    def _create_private_permissions(user, unified_document) -> None:
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
            organization=getattr(user, "organization", None),
            user=user,
        )
