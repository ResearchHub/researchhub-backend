import json

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.models import NoteContent
from note.tests.helpers import create_note
from research_ai.services.note_tools import EDIT_NOTE, READ_NOTE, NoteToolset
from researchhub_access_group.constants import ADMIN, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.registered_report_note_metadata import (
    add_registered_report_prefill_metadata,
)
from researchhub_document.related_models.constants.document_type import (
    REGISTERED_REPORT,
)

TIPTAP_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Updated by the agent"}],
        }
    ],
}


class NoteToolsetTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.viewer = user_model.objects.create_user(
            username="viewer@researchhub_test.com",
            password="password",
            email="viewer@researchhub_test.com",
        )
        self.outsider = user_model.objects.create_user(
            username="outsider@researchhub_test.com",
            password="password",
            email="outsider@researchhub_test.com",
        )

        self.note, self.content = create_note(self.owner, organization=None)
        unified_doc_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=unified_doc_ct,
            object_id=self.note.unified_document.id,
            user=self.owner,
        )
        Permission.objects.create(
            access_type=VIEWER,
            content_type=unified_doc_ct,
            object_id=self.note.unified_document.id,
            user=self.viewer,
        )

        self.toolset = NoteToolset(user=self.owner).as_toolset()

    def test_read_note_returns_content_and_version(self):
        # Act
        result, stop = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})

        # Assert
        self.assertFalse(stop)
        self.assertEqual(result["note_id"], self.note.id)
        self.assertEqual(result["title"], self.note.title)
        self.assertEqual(result["version_id"], self.content.id)
        # The seeded note has plain_text only, so the fallback is included.
        self.assertIsNone(result["content"])
        self.assertEqual(result["plain_text"], "some text")

    def test_read_note_denied_for_user_without_access(self):
        # Arrange
        toolset = NoteToolset(user=self.outsider).as_toolset()

        # Act
        result, _ = toolset.dispatch(READ_NOTE, {"note_id": self.note.id})

        # Assert
        self.assertIn("error", result)

    def test_read_note_unknown_id_returns_error(self):
        # Act
        result, _ = self.toolset.dispatch(READ_NOTE, {"note_id": 999999})

        # Assert
        self.assertIn("error", result)

    def test_edit_note_creates_new_version(self):
        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "content": TIPTAP_DOC,
            },
        )

        # Assert
        self.assertTrue(result.get("saved"))
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, result["version_id"])
        # Stored as a JSON-encoded string (the shape the frontend editor
        # loads), while read_note hands the model back the parsed document.
        self.assertIsInstance(self.note.latest_version.json, str)
        self.assertEqual(json.loads(self.note.latest_version.json), TIPTAP_DOC)
        self.assertEqual(self.note.latest_version.plain_text, "Updated by the agent")
        # The prior version is kept as history.
        self.assertEqual(self.note.notes.count(), 2)

        read, _ = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})
        self.assertEqual(read["content"], TIPTAP_DOC)
        self.assertEqual(read["version_id"], result["version_id"])

    def test_edit_note_rejects_stale_version(self):
        # Arrange: another writer saved a version after our read.
        newer, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "content": TIPTAP_DOC,
            },
        )

        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "content": TIPTAP_DOC,
            },
        )

        # Assert
        self.assertIn("stale version", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, newer["version_id"])

    def test_edit_note_denied_for_viewer(self):
        # Arrange
        toolset = NoteToolset(user=self.viewer).as_toolset()

        # Act
        result, _ = toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "content": TIPTAP_DOC,
            },
        )

        # Assert
        self.assertIn("no edit permission", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, self.content.id)

    def test_edit_note_preserves_registered_report_prefill(self):
        # Arrange: a registered-report draft whose latest version carries
        # publish metadata that the agent's replacement document omits.
        prefill = {"proposal_id": 42}
        self.note.document_type = REGISTERED_REPORT
        self.note.save()
        seeded = NoteContent.objects.create(
            note=self.note,
            json=json.dumps(
                add_registered_report_prefill_metadata(TIPTAP_DOC, prefill)
            ),
            plain_text="seeded",
        )

        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": seeded.id,
                "content": TIPTAP_DOC,
            },
        )

        # Assert
        self.assertTrue(result.get("saved"))
        self.note.refresh_from_db()
        stored = json.loads(self.note.latest_version.json)
        self.assertEqual(stored["attrs"]["registered_report_prefill"], prefill)

    def test_edit_note_rejects_invalid_content(self):
        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "content": {"type": "paragraph"},
            },
        )

        # Assert
        self.assertIn("error", result)
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, self.content.id)

    def test_scoped_toolset_allows_the_scoped_note(self):
        # Arrange
        toolset = NoteToolset(user=self.owner, note_ids={self.note.id}).as_toolset()

        # Act
        result, _ = toolset.dispatch(READ_NOTE, {"note_id": self.note.id})

        # Assert
        self.assertEqual(result["note_id"], self.note.id)

    def test_scoped_toolset_rejects_other_notes_the_user_can_access(self):
        # Arrange: a second note the owner administers, toolset scoped to the
        # first -- the scope must win over the user's own permissions.
        other_note, other_content = create_note(self.owner, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=other_note.unified_document.id,
            user=self.owner,
        )
        toolset = NoteToolset(user=self.owner, note_ids={self.note.id}).as_toolset()

        # Act
        read_result, _ = toolset.dispatch(READ_NOTE, {"note_id": other_note.id})
        edit_result, _ = toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": other_note.id,
                "expected_version_id": other_content.id,
                "content": TIPTAP_DOC,
            },
        )

        # Assert: same not-found error as an inaccessible note, nothing leaked.
        self.assertIn("not found or not accessible", read_result["error"])
        self.assertIn("not found or not accessible", edit_result["error"])
        other_note.refresh_from_db()
        self.assertEqual(other_note.latest_version_id, other_content.id)
