import json

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.models import NoteContent
from note.tests.helpers import create_note
from research_ai.services.note_tools import (
    EDIT_NOTE,
    GET_NOTE_OUTLINE,
    LEGACY_NOTE_MODE,
    READ_NOTE,
    READ_NOTE_SECTION,
    REPLACE_NOTE_SECTION,
    SECTION_NOTE_MODE,
    NoteToolset,
)
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

SECTIONED_DOC = {
    "type": "doc",
    "attrs": {"preserved": True},
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Lead"}]},
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "Methods"}],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Old methods"}],
        },
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "Results"}],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Keep results"}],
        },
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

        self.toolset = NoteToolset(
            user=self.owner, mode=LEGACY_NOTE_MODE
        ).as_toolset()

    def _seed_sectioned_note(self):
        version = NoteContent.objects.create(
            note=self.note,
            json=json.dumps(SECTIONED_DOC),
            plain_text="Lead\nMethods\nOld methods\nResults\nKeep results",
        )
        self.note.refresh_from_db()
        return version

    def test_legacy_mode_exposes_only_full_document_tools(self):
        # Act
        names = self.toolset.names

        # Assert
        self.assertEqual(names, [READ_NOTE, EDIT_NOTE])

    def test_section_mode_exposes_only_section_tools(self):
        # Arrange
        toolset = NoteToolset(
            user=self.owner, mode=SECTION_NOTE_MODE
        ).as_toolset()

        # Act & Assert
        self.assertEqual(
            toolset.names,
            [GET_NOTE_OUTLINE, READ_NOTE_SECTION, REPLACE_NOTE_SECTION],
        )
        result, _ = toolset.dispatch(EDIT_NOTE, {"note_id": self.note.id})
        self.assertEqual(result["error"], "unknown tool: edit_note")

    def test_outline_and_section_read_return_only_addressed_content(self):
        # Arrange
        version = self._seed_sectioned_note()
        toolset = NoteToolset(
            user=self.owner, mode=SECTION_NOTE_MODE
        ).as_toolset()

        # Act
        outline, _ = toolset.dispatch(GET_NOTE_OUTLINE, {"note_id": self.note.id})
        section, _ = toolset.dispatch(
            READ_NOTE_SECTION,
            {"note_id": self.note.id, "section_id": "heading-1"},
        )

        # Assert
        self.assertEqual(outline["version_id"], version.id)
        self.assertEqual(
            [item["section_id"] for item in outline["sections"]],
            ["preamble", "heading-1", "heading-3"],
        )
        self.assertEqual(section["heading"], "Methods")
        self.assertEqual(section["block_count"], 2)
        self.assertEqual(section["content"], SECTIONED_DOC["content"][1:3])

    def test_replace_section_preserves_unread_document_content(self):
        # Arrange
        version = self._seed_sectioned_note()
        toolset = NoteToolset(
            user=self.owner, mode=SECTION_NOTE_MODE
        ).as_toolset()
        replacement = [
            SECTIONED_DOC["content"][1],
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "New methods"}],
            },
        ]

        # Act
        result, _ = toolset.dispatch(
            REPLACE_NOTE_SECTION,
            {
                "note_id": self.note.id,
                "section_id": "heading-1",
                "expected_version_id": version.id,
                "content": replacement,
            },
        )

        # Assert
        self.assertTrue(result["saved"])
        self.note.refresh_from_db()
        stored = json.loads(self.note.latest_version.json)
        self.assertEqual(stored["attrs"], {"preserved": True})
        self.assertEqual(stored["content"][:1], SECTIONED_DOC["content"][:1])
        self.assertEqual(stored["content"][1:3], replacement)
        self.assertEqual(stored["content"][3:], SECTIONED_DOC["content"][3:])
        self.assertEqual(self.note.latest_version.parent_version_id, version.id)

    def test_replace_section_rejects_stale_outline(self):
        # Arrange
        version = self._seed_sectioned_note()
        toolset = NoteToolset(
            user=self.owner, mode=SECTION_NOTE_MODE
        ).as_toolset()
        newer = NoteContent.objects.create(
            note=self.note,
            json=json.dumps(SECTIONED_DOC),
            plain_text="newer",
        )

        # Act
        result, _ = toolset.dispatch(
            REPLACE_NOTE_SECTION,
            {
                "note_id": self.note.id,
                "section_id": "heading-1",
                "expected_version_id": version.id,
                "content": [],
            },
        )

        # Assert
        self.assertIn("stale version", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, newer.id)

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
        toolset = NoteToolset(
            user=self.outsider, mode=LEGACY_NOTE_MODE
        ).as_toolset()

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
        # Attribution for version events and history: who wrote it, through
        # what surface, and from which base version.
        self.assertEqual(self.note.latest_version.created_by, self.owner)
        self.assertEqual(
            self.note.latest_version.created_via, NoteContent.CREATED_VIA_AGENT
        )
        self.assertEqual(self.note.latest_version.parent_version_id, self.content.id)

        read, _ = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})
        self.assertIn("restricted to legacy", read["error"])

    def test_edit_note_rejects_content_that_is_already_structured(self):
        # Arrange
        version = self._seed_sectioned_note()

        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": version.id,
                "content": TIPTAP_DOC,
            },
        )

        # Assert
        self.assertIn("restricted to legacy", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, version.id)

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
        toolset = NoteToolset(
            user=self.viewer, mode=LEGACY_NOTE_MODE
        ).as_toolset()

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
        toolset = NoteToolset(
            user=self.owner, mode=SECTION_NOTE_MODE
        ).as_toolset()

        # Act
        result, _ = toolset.dispatch(
            REPLACE_NOTE_SECTION,
            {
                "note_id": self.note.id,
                "section_id": "body",
                "expected_version_id": seeded.id,
                "content": TIPTAP_DOC["content"],
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
        toolset = NoteToolset(
            user=self.owner,
            mode=LEGACY_NOTE_MODE,
            note_ids={self.note.id},
        ).as_toolset()

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
        toolset = NoteToolset(
            user=self.owner,
            mode=LEGACY_NOTE_MODE,
            note_ids={self.note.id},
        ).as_toolset()

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
