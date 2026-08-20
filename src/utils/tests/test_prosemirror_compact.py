import unittest

from utils.prosemirror import BLOCK_EDITOR, compact_blocks, parse_blocks

# A document the way the frontend editor emits it: every attribute present,
# defaults and all, every text run a node object.
EDITOR_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"id": None, "data-toc-id": None, "textAlign": None, "level": 2},
            "content": [{"type": "text", "text": "Intro"}],
        },
        {
            "type": "paragraph",
            "attrs": {"id": None, "class": None, "textAlign": None},
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "world", "marks": [{"type": "bold"}]},
            ],
        },
        {
            "type": "paragraph",
            "attrs": {"id": None, "class": None, "textAlign": None},
            "content": [{"type": "text", "text": "Plain prose"}],
        },
        {"type": "paragraph", "attrs": {"id": None, "class": None, "textAlign": None}},
        {
            "type": "taskList",
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"checked": True},
                    "content": [
                        {
                            "type": "paragraph",
                            "attrs": {"id": None, "class": None, "textAlign": None},
                            "content": [{"type": "text", "text": "todo"}],
                        }
                    ],
                }
            ],
        },
    ],
}


class CompactBlocksTests(unittest.TestCase):
    def test_compacts_editor_document(self):
        # Act
        blocks = compact_blocks(BLOCK_EDITOR, EDITOR_DOC)

        # Assert: defaults are dropped, plain text is bare strings, and a
        # default paragraph of one plain run is just its text.
        self.assertEqual(
            blocks,
            [
                {"type": "heading", "attrs": {"level": 2}, "content": ["Intro"]},
                {
                    "type": "paragraph",
                    "content": [
                        "Hello ",
                        {
                            "type": "text",
                            "text": "world",
                            "marks": [{"type": "bold"}],
                        },
                    ],
                },
                "Plain prose",
                "",
                {
                    "type": "taskList",
                    "content": [
                        {
                            "type": "taskItem",
                            "attrs": {"checked": True},
                            "content": [{"type": "paragraph", "content": ["todo"]}],
                        }
                    ],
                },
            ],
        )

    def test_paragraph_with_non_default_attrs_stays_a_dict(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"textAlign": "center"},
                    "content": [{"type": "text", "text": "Centered"}],
                }
            ],
        }

        # Act
        blocks = compact_blocks(BLOCK_EDITOR, doc)

        # Assert: the non-default attribute must survive, so no bare string.
        self.assertEqual(
            blocks,
            [
                {
                    "type": "paragraph",
                    "attrs": {"textAlign": "center"},
                    "content": ["Centered"],
                }
            ],
        )

    def test_default_mark_attrs_are_dropped(self):
        # Arrange: a link the way the editor emits it, defaults included.
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "see",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {
                                        "href": "https://example.com",
                                        "target": "_blank",
                                        "rel": "noopener noreferrer nofollow",
                                        "class": "link",
                                        "title": None,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        # Act
        blocks = compact_blocks(BLOCK_EDITOR, doc)

        # Assert
        self.assertEqual(
            blocks[0]["content"][0]["marks"],
            [{"type": "link", "attrs": {"href": "https://example.com"}}],
        )

    def test_ignores_system_owned_root_attrs(self):
        # Arrange: registered-report drafts carry publish metadata in root
        # attrs the schema does not know; it must not make the note unreadable.
        doc = {
            "type": "doc",
            "attrs": {"registered_report_prefill": {"proposal_id": 42}},
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Body"}],
                }
            ],
        }

        # Act
        blocks = compact_blocks(BLOCK_EDITOR, doc)

        # Assert: content read fine; the root attr is simply not surfaced.
        self.assertEqual(blocks, ["Body"])

    def test_rejects_content_outside_the_schema(self):
        # Arrange
        doc = {"type": "doc", "content": [{"type": "legacyWidget"}]}

        # Act & Assert
        with self.assertRaisesRegex(ValueError, "legacyWidget"):
            compact_blocks(BLOCK_EDITOR, doc)


class ParseBlocksTests(unittest.TestCase):
    def test_expands_compact_dialect_to_canonical_blocks(self):
        # Act: a bare string block, and a bare string inside content.
        blocks = parse_blocks(
            BLOCK_EDITOR,
            [
                "New paragraph",
                {"type": "heading", "attrs": {"level": 3}, "content": ["H"]},
            ],
        )

        # Assert: canonical Tiptap dicts with schema defaults filled in.
        self.assertEqual(
            blocks[0],
            {
                "type": "paragraph",
                "attrs": {"id": None, "class": None, "textAlign": None},
                "content": [{"type": "text", "text": "New paragraph"}],
            },
        )
        self.assertEqual(blocks[1]["attrs"]["level"], 3)
        self.assertEqual(blocks[1]["content"], [{"type": "text", "text": "H"}])

    def test_empty_string_block_is_an_empty_paragraph(self):
        # Act
        blocks = parse_blocks(BLOCK_EDITOR, [""])

        # Assert
        self.assertEqual(blocks[0]["type"], "paragraph")
        self.assertNotIn("content", blocks[0])

    def test_round_trip_is_stable(self):
        # Act
        compact = compact_blocks(BLOCK_EDITOR, EDITOR_DOC)
        canonical = parse_blocks(BLOCK_EDITOR, compact)
        recompacted = compact_blocks(
            BLOCK_EDITOR, {"type": "doc", "content": canonical}
        )

        # Assert: compact -> canonical -> compact loses nothing.
        self.assertEqual(recompacted, compact)

    def test_rejects_schema_violations(self):
        # Arrange
        bad_blocks = {
            "unknown attribute": [{"type": "paragraph", "attrs": {"idd": 1}}],
            "unknown node type": [{"type": "widget"}],
            "invalid nesting": [
                {"type": "paragraph", "content": [{"type": "paragraph"}]}
            ],
            "empty inline text": [{"type": "paragraph", "content": [""]}],
        }

        # Act & Assert
        for name, blocks in bad_blocks.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_blocks(BLOCK_EDITOR, blocks)

    def test_rejects_non_list_or_empty_input(self):
        # Act & Assert
        for bad in ("not a list", {}, [], None):
            with (
                self.subTest(repr(bad)),
                self.assertRaisesRegex(ValueError, "non-empty array"),
            ):
                parse_blocks(BLOCK_EDITOR, bad)
