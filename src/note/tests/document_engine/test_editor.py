import copy
import json
import unittest
from pathlib import Path

from note.services.document_engine import InvalidDocumentOperation, NoteDocumentEngine

FIXTURES = Path(__file__).parent / "fixtures"


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.engine = NoteDocumentEngine()
        raw_document = json.loads((FIXTURES / "editor_document.json").read_text())
        self.document = self.engine.validate({"doc": raw_document})["doc"]

    def test_replace_changes_only_the_target_block(self):
        # Arrange
        untouched = copy.deepcopy(self.document["content"][1:])
        replacement = {
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": "replacement-token"}],
        }

        # Act
        result = self.engine.apply(
            {
                "doc": self.document,
                "operations": [
                    {
                        "op": "replace_block",
                        "locator": "heading-1",
                        "node": replacement,
                    }
                ],
            }
        )

        # Assert
        changed = result["doc"]["content"][0]
        self.assertEqual(changed["attrs"]["id"], "heading-1")
        self.assertEqual(changed["attrs"]["level"], 3)
        self.assertEqual(result["doc"]["content"][1:], untouched)
        self.assertIn("replacement-token", result["plain_text"])

    def test_invalid_later_operation_rejects_request_atomically(self):
        # Arrange
        original = copy.deepcopy(self.document)
        operations = [
            {
                "op": "insert_after",
                "locator": "doc:start",
                "node": {"type": "paragraph", "content": []},
            },
            {
                "op": "replace_block",
                "locator": "table-1",
                "node": {"type": "paragraph", "content": []},
            },
        ]

        # Act / Assert
        with self.assertRaises(InvalidDocumentOperation):
            self.engine.apply({"doc": self.document, "operations": operations})
        self.assertEqual(self.document, original)

    def test_opaque_blocks_can_move_and_delete(self):
        # Arrange
        table = copy.deepcopy(self.document["content"][10])

        # Act
        moved = self.engine.apply(
            {
                "doc": self.document,
                "operations": [
                    {"op": "move_block", "locator": "table-1", "after": "heading-1"}
                ],
            }
        )["doc"]
        deleted = self.engine.apply(
            {
                "doc": moved,
                "operations": [{"op": "delete_block", "locator": "table-1"}],
            }
        )["doc"]

        # Assert
        self.assertEqual(moved["content"][1], table)
        self.assertNotIn(table, deleted["content"])

    def test_move_resolves_index_destination_before_removing_source(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {"type": "horizontalRule"},
                {"type": "imageBlock", "attrs": {"src": "one"}},
                {"type": "youtube", "attrs": {"src": "two"}},
            ],
        }

        # Act
        result = self.engine.apply(
            {
                "doc": doc,
                "operations": [{"op": "move_block", "locator": "i:1", "after": "i:2"}],
            }
        )["doc"]

        # Assert
        self.assertEqual(
            [node["type"] for node in result["content"]],
            ["horizontalRule", "youtube", "imageBlock"],
        )

    def test_created_attributes_are_canonicalized(self):
        # Arrange
        image = {
            "type": "imageBlock",
            "attrs": {"src": "https://example.test/new.png", "alt": "new image"},
        }
        paragraph = {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "linked",
                    "marks": [
                        {
                            "type": "link",
                            "attrs": {"href": "https://example.test/reference"},
                        },
                        {"type": "highlight", "attrs": {"color": "#AABBCC"}},
                    ],
                }
            ],
        }

        # Act
        result = self.engine.apply(
            {
                "doc": self.document,
                "operations": [
                    {"op": "insert_after", "locator": "doc:start", "node": image},
                    {
                        "op": "replace_block",
                        "locator": "paragraph-1",
                        "node": paragraph,
                    },
                ],
            }
        )["doc"]

        # Assert
        self.assertEqual(
            result["content"][0]["attrs"],
            {
                "src": "https://example.test/new.png",
                "width": "100%",
                "align": "center",
                "alt": "new image",
            },
        )
        marks = result["content"][2]["content"][0]["marks"]
        self.assertEqual(marks[0]["attrs"]["target"], "_blank")
        self.assertEqual(marks[1]["attrs"]["color"], "#aabbcc")

    def test_invalid_created_content_is_rejected(self):
        invalid_nodes = [
            {"type": "paragraph", "attrs": {"id": "model-id"}},
            {"type": "heading", "attrs": {"level": 7}},
            {"type": "imageBlock", "attrs": {"src": "http://example.test/a.png"}},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "styled",
                        "marks": [{"type": "textStyle", "attrs": {"color": "red"}}],
                    }
                ],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": ""}]},
            {"type": "table", "attrs": {"id": "invented"}},
        ]
        for node in invalid_nodes:
            with self.subTest(node=node):
                # Arrange
                operation = {
                    "op": "insert_after",
                    "locator": "doc:start",
                    "node": node,
                }

                # Act / Assert
                with self.assertRaises(InvalidDocumentOperation):
                    self.engine.apply({"doc": self.document, "operations": [operation]})

    def test_replace_note_preserves_verbatim_opaque_blocks(self):
        # Arrange
        submitted = {
            "type": "doc",
            "content": [
                copy.deepcopy(self.document["content"][10]),
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "new-block"}],
                },
            ],
        }

        # Act
        result = self.engine.apply(
            {
                "doc": self.document,
                "operations": [{"op": "replace_note", "doc": submitted}],
            }
        )["doc"]

        # Assert
        self.assertEqual(result["content"][0], self.document["content"][10])
        self.assertEqual(result["content"][1]["content"][0]["text"], "new-block")
        self.assertIn("id", result["content"][1]["attrs"])

    def test_replace_note_rejects_modified_opaque_blocks(self):
        # Arrange
        modified_table = copy.deepcopy(self.document["content"][10])
        modified_table["content"][0]["content"][0]["attrs"]["style"] = "color:red"
        submitted = {"type": "doc", "content": [modified_table]}

        # Act / Assert
        with self.assertRaises(InvalidDocumentOperation):
            self.engine.apply(
                {
                    "doc": self.document,
                    "operations": [{"op": "replace_note", "doc": submitted}],
                }
            )
