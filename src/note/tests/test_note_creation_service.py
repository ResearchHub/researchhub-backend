from django.contrib.auth import get_user_model
from django.test import TestCase

from note.services.note_creation_service import NoteCreationService
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_document.related_models.constants.document_type import (
    NOTE,
    PREREGISTRATION,
)


class NoteCreationServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other = get_user_model().objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )

    def test_creates_a_private_empty_note_in_the_users_personal_org(self):
        # Act
        note = NoteCreationService().create_private_note(
            created_by=self.user, title="Ideas"
        )

        # Assert
        self.assertEqual(note.title, "Ideas")
        self.assertEqual(note.document_type, NOTE)
        self.assertEqual(note.created_by, self.user)
        self.assertEqual(note.organization, self.user.organization)
        self.assertIsNone(note.latest_version)
        self.assertEqual(note.unified_document.document_type, NOTE)
        permissions = note.unified_document.permissions
        self.assertTrue(permissions.filter(user=self.user, access_type=ADMIN).exists())
        self.assertTrue(
            permissions.filter(
                organization=self.user.organization, access_type=NO_ACCESS
            ).exists()
        )
        self.assertTrue(permissions.has_user(self.user))
        self.assertFalse(permissions.has_user(self.other))

    def test_document_type_and_grant_are_recorded(self):
        # Act
        note = NoteCreationService().create_private_note(
            created_by=self.user, title="Proposal", document_type=PREREGISTRATION
        )

        # Assert
        self.assertEqual(note.document_type, PREREGISTRATION)
        self.assertIsNone(note.selected_grant)

    def test_ownerless_note_has_no_permissions(self):
        # Act
        note = NoteCreationService().create_private_note(
            created_by=None, title="System"
        )

        # Assert
        self.assertIsNone(note.created_by)
        self.assertIsNone(note.organization)
        self.assertFalse(note.unified_document.permissions.exists())
