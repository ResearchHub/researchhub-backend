from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

from note.models import NoteContent
from note.services.note_creation_service import NoteCreationService
from researchhub_access_group.constants import ADMIN, EDITOR, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.services.note_publication_service import (
    NotePublicationService,
)
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockMixin


class NotePublicationTests(AWSMockMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.owner = create_random_default_user("note_publication_owner")
        self.other_user = create_random_default_user("note_publication_other")
        self.note = NoteCreationService().create_private_note(
            created_by=self.owner, title="Private unpublished note"
        )
        self.secret = "Private draft body that must not be disclosed"
        NoteContent.objects.create(note=self.note, plain_text=self.secret)
        self.payload = {
            "document_type": DISCUSSION,
            "title": "Public post with a sufficiently long title",
            "renderable_text": "Public post content that is long enough to publish. "
            * 2,
            "full_src": "Public post content",
            "is_public": True,
            "note_id": self.note.pk,
        }

    def _grant_permission(self, access_type):
        Permission.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document_id,
            user=self.other_user,
            access_type=access_type,
        )

    def test_other_user_cannot_publish_or_read_private_note_through_a_post(self):
        for document_type in (DISCUSSION, GRANT, PREREGISTRATION):
            with self.subTest(document_type=document_type):
                # Arrange
                self.client.force_authenticate(self.other_user)
                document_count = ResearchhubUnifiedDocument.objects.count()

                # Act
                response = self.client.post(
                    "/api/researchhubpost/",
                    {**self.payload, "document_type": document_type},
                )

                # Assert
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertNotIn(self.secret, str(response.data))
                self.assertFalse(
                    ResearchhubPost.objects.filter(note=self.note).exists()
                )
                self.assertEqual(
                    ResearchhubUnifiedDocument.objects.count(), document_count
                )

    def test_read_permission_does_not_allow_publication(self):
        # Arrange
        self._grant_permission(VIEWER)
        self.client.force_authenticate(self.other_user)

        # Act
        response = self.client.post("/api/researchhubpost/", self.payload)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(ResearchhubPost.objects.filter(note=self.note).exists())

    def test_owner_can_publish_private_note(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post("/api/researchhubpost/", self.payload)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            ResearchhubPost.objects.get(pk=response.data["id"]).note, self.note
        )

    def test_note_admin_and_editor_can_publish(self):
        for access_type in (ADMIN, EDITOR):
            with self.subTest(access_type=access_type):
                # Arrange
                note = NoteCreationService().create_private_note(
                    created_by=self.owner, title=f"Draft for {access_type}"
                )
                Permission.objects.create(
                    content_type=ContentType.objects.get_for_model(
                        ResearchhubUnifiedDocument
                    ),
                    object_id=note.unified_document_id,
                    user=self.other_user,
                    access_type=access_type,
                )
                self.client.force_authenticate(self.other_user)

                # Act
                response = self.client.post(
                    "/api/researchhubpost/", {**self.payload, "note_id": note.pk}
                )

                # Assert
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    ResearchhubPost.objects.get(pk=response.data["id"]).note, note
                )

    def test_already_published_note_is_rejected_without_creating_another_post(self):
        # Arrange
        original = create_post(created_by=self.owner)
        original.note = self.note
        original.save(update_fields=["note"])
        self.client.force_authenticate(self.owner)
        post_count = ResearchhubPost.objects.count()

        # Act
        response = self.client.post("/api/researchhubpost/", self.payload)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ResearchhubPost.objects.count(), post_count)
        original.refresh_from_db()
        self.assertEqual(original.note, self.note)

    def test_invalid_note_ids_are_rejected(self):
        for note_id in ("invalid", self.note.pk + 1000000):
            with self.subTest(note_id=note_id):
                # Arrange
                self.client.force_authenticate(self.owner)

                # Act
                response = self.client.post(
                    "/api/researchhubpost/", {**self.payload, "note_id": note_id}
                )

                # Assert
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertFalse(ResearchhubPost.objects.exists())

    def test_removed_note_cannot_be_published(self):
        # Arrange
        self.note.unified_document.is_removed = True
        self.note.unified_document.save(update_fields=["is_removed"])
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post("/api/researchhubpost/", self.payload)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(ResearchhubPost.objects.filter(note=self.note).exists())

    def test_post_without_note_is_still_supported(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post(
            "/api/researchhubpost/", {**self.payload, "note_id": None}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(ResearchhubPost.objects.get(pk=response.data["id"]).note)

    def test_service_requires_an_authenticated_publisher(self):
        # Arrange
        service = NotePublicationService()

        # Act
        with self.assertRaises(PermissionDenied):
            service.get_note_for_publication(self.note.pk, None)

        # Assert
        self.assertFalse(ResearchhubPost.objects.filter(note=self.note).exists())
