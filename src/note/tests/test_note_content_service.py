import json
import unittest

from django.contrib.auth import get_user_model
from django.test import TestCase

from note.related_models.note_model import NoteContent
from note.services.note_content_service import NoteContentService, extract_plain_text
from note.tests.helpers import create_note
from researchhub_document.registered_report_note_metadata import (
    add_registered_report_prefill_metadata,
)
from researchhub_document.related_models.constants.document_type import (
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

TIPTAP_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "Title"}],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "marks": [{"type": "bold"}], "text": "world"},
            ],
        },
    ],
}


class ExtractPlainTextTests(unittest.TestCase):
    def test_joins_blocks_with_newlines(self):
        # Act
        text = extract_plain_text(TIPTAP_DOC)

        # Assert
        self.assertEqual(text, "Title\nHello world")

    def test_malformed_input_returns_empty_string(self):
        # Act & Assert
        self.assertEqual(extract_plain_text(None), "")
        self.assertEqual(extract_plain_text("not a doc"), "")
        self.assertEqual(extract_plain_text({"type": "doc"}), "")
        self.assertEqual(
            extract_plain_text({"type": "doc", "content": [{"type": "text"}]}), ""
        )


class NoteContentServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="svc@researchhub_test.com",
            password="password",
            email="svc@researchhub_test.com",
        )
        self.note, self.initial_content = create_note(self.user, organization=None)
        self.service = NoteContentService()

    def test_create_version_appends_and_updates_latest_version(self):
        # Act
        version = self.service.create_version(self.note, TIPTAP_DOC)

        # Assert
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, version.id)
        self.assertNotEqual(version.id, self.initial_content.id)
        # Stored as a JSON-encoded string: the shape the frontend editor's
        # JSON.parse(contentJson) load path expects.
        self.assertIsInstance(version.json, str)
        self.assertEqual(json.loads(version.json), TIPTAP_DOC)
        self.assertEqual(version.plain_text, "Title\nHello world")
        self.assertEqual(self.note.notes.count(), 2)

    def test_create_version_rejects_non_document_content(self):
        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.create_version(self.note, {"type": "paragraph"})
        with self.assertRaises(ValueError):
            self.service.create_version(self.note, "not json")

    def test_create_version_rejects_published_registered_report(self):
        # Arrange
        ResearchhubPost.objects.create(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            note=self.note,
            unified_document=self.note.unified_document,
        )

        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.create_version(self.note, TIPTAP_DOC)


PREFILL = {
    "author_ids": [7],
    "image": None,
    "preview_img": None,
    "proposal_id": 42,
}


class RegisteredReportPrefillTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="prefill@researchhub_test.com",
            password="password",
            email="prefill@researchhub_test.com",
        )
        self.note, _ = create_note(self.user, organization=None)
        self.note.document_type = REGISTERED_REPORT
        self.note.save()
        self.service = NoteContentService()
        # Seed the draft the way draft creation does: the prefill attr on the
        # document root, persisted as a JSON-encoded string.
        seeded = add_registered_report_prefill_metadata(TIPTAP_DOC, PREFILL)
        NoteContent.objects.create(
            note=self.note, json=json.dumps(seeded), plain_text="seeded"
        )
        self.note.refresh_from_db()

    def test_create_version_restores_dropped_prefill(self):
        # Act: the replacement document omits the prefill attr entirely.
        version = self.service.create_version(self.note, TIPTAP_DOC)

        # Assert
        stored = json.loads(version.json)
        self.assertEqual(stored["attrs"]["registered_report_prefill"], PREFILL)
        self.assertEqual(stored["content"], TIPTAP_DOC["content"])

    def test_create_version_overrides_tampered_prefill(self):
        # Arrange
        tampered = add_registered_report_prefill_metadata(
            TIPTAP_DOC, {"proposal_id": 999}
        )

        # Act
        version = self.service.create_version(self.note, tampered)

        # Assert
        stored = json.loads(version.json)
        self.assertEqual(stored["attrs"]["registered_report_prefill"], PREFILL)

    def test_create_version_without_prior_prefill_saves_content_as_is(self):
        # Arrange: a registered-report note whose history has no prefill.
        note, _ = create_note(self.user, organization=None)
        note.document_type = REGISTERED_REPORT
        note.save()

        # Act
        version = self.service.create_version(note, TIPTAP_DOC)

        # Assert
        self.assertEqual(json.loads(version.json), TIPTAP_DOC)
