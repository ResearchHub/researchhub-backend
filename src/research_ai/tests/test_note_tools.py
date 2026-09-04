import json

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.models import NoteContent
from note.tests.helpers import create_note
from research_ai.services.note_tools import (
    CREATE_NOTE,
    EDIT_NOTE,
    READ_NOTE,
    NoteToolset,
)
from researchhub_access_group.constants import ADMIN, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)

# A two-block document the way the frontend editor stores it (defaults spelled
# out), used to seed notes with structured content.
EDITOR_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"id": None, "data-toc-id": None, "textAlign": None, "level": 2},
            "content": [{"type": "text", "text": "Title"}],
        },
        {
            "type": "paragraph",
            "attrs": {"id": None, "class": None, "textAlign": None},
            "content": [{"type": "text", "text": "Original body"}],
        },
    ],
}


def _insert(blocks, at=0):
    return [{"op": "insert", "at": at, "blocks": blocks}]


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

    def _seed_version(self, document) -> NoteContent:
        version = NoteContent.objects.create(
            note=self.note,
            json=json.dumps(document),
            plain_text="seeded",
        )
        self.note.refresh_from_db()
        return version

    # -- read ---------------------------------------------------------------

    def test_read_note_returns_compact_indexed_blocks(self):
        # Arrange
        seeded = self._seed_version(EDITOR_DOC)

        # Act
        result, stop = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})

        # Assert: blocks come back compact -- defaults dropped, plain
        # paragraphs as bare strings -- keyed by their index.
        self.assertFalse(stop)
        self.assertEqual(result["note_id"], self.note.id)
        self.assertEqual(result["title"], self.note.title)
        self.assertEqual(result["version_id"], seeded.id)
        self.assertEqual(result["block_count"], 2)
        self.assertEqual(
            result["blocks"],
            {
                "0": {"type": "heading", "attrs": {"level": 2}, "content": ["Title"]},
                "1": "Original body",
            },
        )
        self.assertNotIn("plain_text", result)

    def test_read_note_without_content_returns_null_blocks(self):
        # Act: the seeded note from create_note has no content JSON.
        result, _ = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})

        # Assert: note content lives in version JSON only; there is no
        # plain-text fallback.
        self.assertEqual(result["version_id"], self.content.id)
        self.assertIsNone(result["blocks"])
        self.assertEqual(result["block_count"], 0)
        self.assertNotIn("plain_text", result)

    def test_read_note_reports_content_outside_the_schema_as_error(self):
        # Arrange: stored content is expected to parse (pre-schema notes were
        # cleaned up); a note that does not must fail loudly, not degrade.
        self._seed_version({"type": "doc", "content": [{"type": "legacyWidget"}]})

        # Act
        result, _ = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})

        # Assert
        self.assertIn("could not be read", result["error"])

    def test_read_note_returns_bounded_windows_with_global_indices(self):
        # Arrange: enough compact paragraph blocks to require two reads.
        document = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": f"Block {i}"}],
                }
                for i in range(75)
            ],
        }
        seeded = self._seed_version(document)

        # Act
        first, _ = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})
        second, _ = self.toolset.dispatch(
            READ_NOTE,
            {
                "note_id": self.note.id,
                "version_id": seeded.id,
                "start_block": 50,
                "max_blocks": 25,
            },
        )

        # Assert
        self.assertEqual(first["version_id"], seeded.id)
        self.assertEqual(first["block_count"], 75)
        self.assertEqual(first["returned_block_count"], 50)
        self.assertEqual(first["next_start_block"], 50)
        self.assertEqual(first["blocks"]["49"], "Block 49")
        self.assertEqual(second["start_block"], 50)
        self.assertEqual(second["returned_block_count"], 25)
        self.assertIsNone(second["next_start_block"])
        self.assertEqual(second["blocks"]["50"], "Block 50")
        self.assertEqual(second["blocks"]["74"], "Block 74")

    def test_read_note_continuation_stays_on_the_requested_version(self):
        # Arrange: read the first page, then append a newer version whose
        # insertion would shift every later global block index.
        original = self._seed_version(
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": f"Block {i}"}],
                    }
                    for i in range(75)
                ],
            }
        )
        first, _ = self.toolset.dispatch(READ_NOTE, {"note_id": self.note.id})
        edit, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": original.id,
                "edits": _insert(["New first block"]),
            },
        )

        # Act
        continuation, _ = self.toolset.dispatch(
            READ_NOTE,
            {
                "note_id": self.note.id,
                "version_id": first["version_id"],
                "start_block": first["next_start_block"],
            },
        )

        # Assert: the page uses the original immutable content even though the
        # note now has a newer latest version.
        self.assertTrue(edit["saved"])
        self.assertNotEqual(edit["version_id"], original.id)
        self.assertEqual(continuation["version_id"], original.id)
        self.assertEqual(continuation["block_count"], 75)
        self.assertEqual(continuation["blocks"]["50"], "Block 50")

    def test_read_note_continuation_requires_version_id(self):
        # Act
        result, _ = self.toolset.dispatch(
            READ_NOTE, {"note_id": self.note.id, "start_block": 1}
        )

        # Assert
        self.assertIn("version_id is required", result["error"])

    def test_read_note_rejects_version_from_another_note(self):
        # Arrange
        other_note, other_version = create_note(self.owner, organization=None)

        # Act
        result, _ = self.toolset.dispatch(
            READ_NOTE,
            {"note_id": self.note.id, "version_id": other_version.id},
        )

        # Assert: a version can only be read through its own accessible note.
        self.assertNotEqual(other_note.id, self.note.id)
        self.assertIn("not found for note", result["error"])

    def test_read_note_rejects_invalid_bounds(self):
        # Act
        too_wide, _ = self.toolset.dispatch(
            READ_NOTE, {"note_id": self.note.id, "max_blocks": 51}
        )
        negative, _ = self.toolset.dispatch(
            READ_NOTE, {"note_id": self.note.id, "start_block": -1}
        )

        # Assert
        self.assertIn("between 1 and 50", too_wide["error"])
        self.assertIn("at least 0", negative["error"])

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

    # -- edit ---------------------------------------------------------------

    def test_edit_note_inserts_into_a_note_without_structured_content(self):
        # Act: compact dialect -- a bare string is a paragraph.
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "edits": _insert(["Written by the agent"]),
            },
        )

        # Assert
        self.assertTrue(result.get("saved"))
        self.assertEqual(result["block_count"], 1)
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, result["version_id"])
        # Stored as a JSON-encoded string (the shape the frontend editor
        # loads) holding the canonical document, defaults filled in.
        self.assertIsInstance(self.note.latest_version.json, str)
        stored = json.loads(self.note.latest_version.json)
        self.assertEqual(stored["type"], "doc")
        self.assertEqual(
            stored["content"][0]["content"],
            [{"type": "text", "text": "Written by the agent"}],
        )
        self.assertIn("attrs", stored["content"][0])
        self.assertEqual(self.note.latest_version.plain_text, "Written by the agent")
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
        self.assertEqual(read["blocks"], {"0": "Written by the agent"})
        self.assertEqual(read["version_id"], result["version_id"])

    def test_edit_note_touches_only_the_addressed_blocks(self):
        # Arrange
        seeded = self._seed_version(EDITOR_DOC)

        # Act: replace the body, keep the heading, append a footnote -- all
        # against the indices from the read.
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": seeded.id,
                "edits": [
                    {"op": "replace", "from": 1, "to": 1, "blocks": ["New body"]},
                    {"op": "insert", "at": 2, "blocks": ["Footnote"]},
                ],
            },
        )

        # Assert
        self.assertTrue(result.get("saved"))
        self.assertEqual(result["block_count"], 3)
        self.note.refresh_from_db()
        stored = json.loads(self.note.latest_version.json)
        # The untouched heading is spliced through byte-identical.
        self.assertEqual(stored["content"][0], EDITOR_DOC["content"][0])
        self.assertEqual(
            [block["type"] for block in stored["content"]],
            ["heading", "paragraph", "paragraph"],
        )
        self.assertEqual(
            self.note.latest_version.plain_text, "Title\nNew body\nFootnote"
        )

    def test_edit_note_stores_a_clean_document_root(self):
        # Arrange: root metadata is not part of the agent surface; whatever
        # the stored root held, agent versions carry type and content only.
        seeded = self._seed_version(
            {"content": EDITOR_DOC["content"], "attrs": {"stray": 1}}
        )

        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": seeded.id,
                "edits": [{"op": "replace", "from": 1, "to": 1, "blocks": ["Fixed"]}],
            },
        )

        # Assert
        self.assertTrue(result.get("saved"))
        self.note.refresh_from_db()
        stored = json.loads(self.note.latest_version.json)
        self.assertEqual(sorted(stored), ["content", "type"])
        self.assertEqual(stored["type"], "doc")

    def test_edit_note_rejects_blocks_outside_the_schema(self):
        # Arrange
        seeded = self._seed_version(EDITOR_DOC)

        # Act: a misspelled attribute the editor would silently drop.
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": seeded.id,
                "edits": [
                    {
                        "op": "replace",
                        "from": 1,
                        "to": 1,
                        "blocks": [{"type": "paragraph", "attrs": {"idd": "x"}}],
                    }
                ],
            },
        )

        # Assert: the error names the edit and the attribute; nothing saved.
        self.assertIn("edits[0]", result["error"])
        self.assertIn("idd", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, seeded.id)

    def test_edit_note_rejects_out_of_range_indices(self):
        # Arrange
        seeded = self._seed_version(EDITOR_DOC)

        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": seeded.id,
                "edits": [{"op": "delete", "from": 5, "to": 5}],
            },
        )

        # Assert
        self.assertIn("block indices run 0..1", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, seeded.id)

    def test_edit_note_rejects_emptying_the_note(self):
        # Arrange
        seeded = self._seed_version(EDITOR_DOC)

        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": seeded.id,
                "edits": [{"op": "delete", "from": 0, "to": 1}],
            },
        )

        # Assert
        self.assertIn("empty", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, seeded.id)

    def test_edit_note_rejects_missing_edits(self):
        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {"note_id": self.note.id, "expected_version_id": self.content.id},
        )

        # Assert
        self.assertIn("edits must be a non-empty array", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, self.content.id)

    def test_edit_note_rejects_stale_version(self):
        # Arrange: another writer saved a version after our read.
        newer, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "edits": _insert(["First edit"]),
            },
        )

        # Act
        result, _ = self.toolset.dispatch(
            EDIT_NOTE,
            {
                "note_id": self.note.id,
                "expected_version_id": self.content.id,
                "edits": _insert(["Second edit"]),
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
                "edits": _insert(["Not allowed"]),
            },
        )

        # Assert
        self.assertIn("no edit permission", result["error"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, self.content.id)

    # -- scoping ------------------------------------------------------------

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
                "edits": _insert(["Out of scope"]),
            },
        )

        # Assert: same not-found error as an inaccessible note, nothing leaked.
        self.assertIn("not found or not accessible", read_result["error"])
        self.assertIn("not found or not accessible", edit_result["error"])
        other_note.refresh_from_db()
        self.assertEqual(other_note.latest_version_id, other_content.id)


class NoteToolsetCreateNoteTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.created = []

        def creator(title, document_type):
            note, _content = create_note(self.owner, organization=None, title=title)
            note.document_type = document_type
            note.save(update_fields=["document_type"])
            Permission.objects.create(
                access_type=ADMIN,
                content_type=ContentType.objects.get_for_model(
                    ResearchhubUnifiedDocument
                ),
                object_id=note.unified_document.id,
                user=self.owner,
            )
            self.created.append(note)
            return note

        self.toolset = NoteToolset(
            user=self.owner, note_ids=set(), note_creator=creator
        )
        self.tools = {tool.name: tool for tool in self.toolset.build_tools()}

    def test_create_note_is_offered_only_with_a_creator(self):
        # Act
        without = {tool.name for tool in NoteToolset(user=self.owner).build_tools()}

        # Assert
        self.assertIn(CREATE_NOTE, self.tools)
        self.assertNotIn(CREATE_NOTE, without)

    def test_create_note_returns_the_note_and_widens_the_scope(self):
        # Arrange
        outside, _content = create_note(self.owner, organization=None)

        # Act
        result = self.tools[CREATE_NOTE].handler(
            {"title": "  New   idea ", "kind": "preregistration"}
        )
        read = self.tools[READ_NOTE].handler({"note_id": result["note_id"]})
        outside_read = self.tools[READ_NOTE].handler({"note_id": outside.id})

        # Assert
        self.assertEqual(result["title"], "New idea")
        self.assertEqual(result["note_id"], self.created[0].id)
        self.assertEqual(result["kind"], "preregistration")
        self.assertEqual(result["document_type"], PREREGISTRATION)
        self.assertIsNone(result["version_id"])
        self.assertEqual(read["title"], "New idea")
        self.assertIn("error", outside_read)

    def test_create_note_rejects_a_blank_title(self):
        # Act
        result = self.tools[CREATE_NOTE].handler({"title": "   ", "kind": "grant"})

        # Assert
        self.assertIn("error", result)
        self.assertEqual(self.created, [])

    def test_create_note_requires_a_supported_kind(self):
        # Act
        missing = self.tools[CREATE_NOTE].handler({"title": "Idea"})
        unknown = self.tools[CREATE_NOTE].handler({"title": "Idea", "kind": "note"})
        grant = self.tools[CREATE_NOTE].handler({"title": "Call", "kind": "grant"})

        # Assert
        self.assertIn("error", missing)
        self.assertIn("error", unknown)
        self.assertEqual(grant["document_type"], GRANT)
        self.assertEqual(len(self.created), 1)

    def test_create_note_reports_creator_failures_to_the_model(self):
        # Arrange
        def failing(title, document_type):
            raise RuntimeError("database is away")

        toolset = NoteToolset(user=self.owner, note_ids=set(), note_creator=failing)
        create = {tool.name: tool for tool in toolset.build_tools()}[CREATE_NOTE]

        # Act
        result = create.handler({"title": "Anything", "kind": "grant"})

        # Assert
        self.assertIn("database is away", result["error"])
