import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.models import NoteContent
from note.services.editable_note import UnsupportedEditableNoteError
from note.services.note_content_service import (
    NoteContentService,
    NoteEditBlocked,
    NoteEditDenied,
    NoteVersionConflict,
)
from note.tests.helpers import create_note
from researchhub_access_group.constants import ADMIN, EDITOR, MEMBER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    REGISTERED_REPORT,
)
from user.models import Organization


class NoteContentServiceTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Notebook", slug=f"notebook-{uuid.uuid4().hex}"
        )
        self.user = get_user_model().objects.create_user(
            username=f"owner-{uuid.uuid4().hex}",
            email=f"owner-{uuid.uuid4().hex}@example.com",
        )
        self.note, self.initial_version = create_note(
            self.user, self.organization, body="Initial"
        )
        self.document_content_type = ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        )
        Permission.objects.create(
            access_type=ADMIN,
            content_type=self.document_content_type,
            object_id=self.note.unified_document_id,
            user=self.user,
        )
        self.service = NoteContentService()
        self.doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Updated note"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Updated"}],
                },
            ],
        }

    def test_save_version_writes_encoded_json_and_updates_latest_version(self):
        # Arrange
        initial_count = NoteContent.objects.filter(note=self.note).count()

        # Act
        version = self.service.save_version(
            self.note,
            self.doc,
            plain_text="Updated note\n\nUpdated",
            user=self.user,
            expected_version_id=self.initial_version.id,
        )
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(
            NoteContent.objects.filter(note=self.note).count(), initial_count + 1
        )
        self.assertEqual(self.note.latest_version_id, version.id)
        self.assertIsInstance(version.json, str)
        self.assertEqual(json.loads(version.json), self.doc)
        self.assertEqual(version.plain_text, "Updated note\n\nUpdated")

    def test_save_version_rejects_stale_expected_version(self):
        # Arrange
        current = self.service.save_version(
            self.note,
            self.doc,
            plain_text="Updated note\n\nUpdated",
            user=self.user,
            expected_version_id=self.initial_version.id,
        )

        # Act / Assert
        with self.assertRaises(NoteVersionConflict) as raised:
            self.service.save_version(
                self.note,
                self.doc,
                plain_text="Updated note\n\nUpdated",
                user=self.user,
                expected_version_id=self.initial_version.id,
            )
        self.assertEqual(raised.exception.current_version_id, current.id)

    def test_save_version_rejects_non_editor(self):
        # Arrange
        other_user = get_user_model().objects.create_user(
            username=f"viewer-{uuid.uuid4().hex}",
            email=f"viewer-{uuid.uuid4().hex}@example.com",
        )

        # Act / Assert
        with self.assertRaises(NoteEditDenied):
            self.service.save_version(
                self.note,
                self.doc,
                plain_text="Updated note\n\nUpdated",
                user=other_user,
                expected_version_id=self.initial_version.id,
            )

    def test_save_version_allows_direct_editor_permission(self):
        # Arrange
        editor = get_user_model().objects.create_user(
            username=f"editor-{uuid.uuid4().hex}",
            email=f"editor-{uuid.uuid4().hex}@example.com",
        )
        Permission.objects.create(
            access_type=EDITOR,
            content_type=self.document_content_type,
            object_id=self.note.unified_document_id,
            user=editor,
        )

        # Act
        version = self.service.save_version(
            self.note,
            self.doc,
            plain_text="Updated note\n\nUpdated",
            user=editor,
            expected_version_id=self.initial_version.id,
        )

        # Assert
        self.assertEqual(version.note_id, self.note.id)

    def test_save_version_allows_editor_by_organization_permission(self):
        # Arrange
        member = get_user_model().objects.create_user(
            username=f"member-{uuid.uuid4().hex}",
            email=f"member-{uuid.uuid4().hex}@example.com",
        )
        organization_content_type = ContentType.objects.get_for_model(Organization)
        Permission.objects.create(
            access_type=MEMBER,
            content_type=organization_content_type,
            object_id=self.organization.id,
            user=member,
        )
        Permission.objects.create(
            access_type=EDITOR,
            content_type=self.document_content_type,
            object_id=self.note.unified_document_id,
            organization=self.organization,
        )

        # Act
        version = self.service.save_version(
            self.note,
            self.doc,
            plain_text="Updated note\n\nUpdated",
            user=member,
            expected_version_id=self.initial_version.id,
        )

        # Assert
        self.assertEqual(version.note_id, self.note.id)

    def test_save_version_blocks_published_registered_report(self):
        # Arrange
        post = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Published report",
        )
        post.note = self.note
        post.save(update_fields=["note"])

        # Act / Assert
        with self.assertRaises(NoteEditBlocked):
            self.service.save_version(
                self.note,
                self.doc,
                plain_text="Updated note\n\nUpdated",
                user=self.user,
                expected_version_id=self.initial_version.id,
            )

    def test_save_version_rejects_non_editable_note_without_writing(self):
        # Arrange
        legacy_doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph"},
                {"type": "paragraph"},
            ],
        }
        initial_count = NoteContent.objects.filter(note=self.note).count()

        # Act / Assert
        with self.assertRaises(UnsupportedEditableNoteError):
            self.service.save_version(
                self.note,
                legacy_doc,
                plain_text="Legacy",
                user=self.user,
                expected_version_id=self.initial_version.id,
            )
        self.assertEqual(
            NoteContent.objects.filter(note=self.note).count(), initial_count
        )

    @patch("note.related_models.note_model.Note.notify_note_updated_title")
    def test_set_title_updates_and_notifies(self, notify):
        # Arrange
        title = "Revised title"

        # Act
        result = self.service.set_title(self.note, title, user=self.user)

        # Assert
        self.note.refresh_from_db()
        self.assertEqual(result.title, title)
        self.assertEqual(self.note.title, title)
        notify.assert_called_once_with()

    def test_set_title_rejects_non_editor(self):
        # Arrange
        other_user = get_user_model().objects.create_user(
            username=f"other-{uuid.uuid4().hex}",
            email=f"other-{uuid.uuid4().hex}@example.com",
        )

        # Act / Assert
        with self.assertRaises(NoteEditDenied):
            self.service.set_title(self.note, "Denied", user=other_user)
