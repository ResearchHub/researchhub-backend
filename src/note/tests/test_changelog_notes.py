from rest_framework.test import APITestCase

from note.models import Note
from researchhub_document.related_models.constants.document_type import CHANGELOG
from user.tests.helpers import create_random_default_user


class ChangelogNoteTests(APITestCase):
    def _create_changelog_note(self, user):
        self.client.force_authenticate(user)
        org = self.client.post("/api/organization/", {"name": "changelog org"}).data
        return self.client.post(
            "/api/note/",
            {
                "document_type": CHANGELOG,
                "grouping": "WORKSPACE",
                "organization_slug": org["slug"],
                "title": "October changelog",
            },
        )

    def test_moderator_creates_changelog_note(self):
        # Arrange
        moderator = create_random_default_user("note_mod", moderator=True)

        # Act
        response = self._create_changelog_note(moderator)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["document_type"], CHANGELOG)

    def test_non_moderator_cannot_create_changelog_note(self):
        # Arrange
        user = create_random_default_user("note_user")

        # Act
        response = self._create_changelog_note(user)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Note.objects.filter(created_by=user).exists())
