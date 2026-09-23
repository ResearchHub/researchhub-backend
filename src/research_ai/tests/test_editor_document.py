"""Agent documents should already have the structure the editor creates."""

import unittest
from uuid import UUID

from research_ai.services.editor_document import prepare_agent_document
from utils.prosemirror import BLOCK_EDITOR, parse_document


class PrepareAgentDocumentTests(unittest.TestCase):
    def test_assigns_ids_recursively_and_adds_a_trailing_paragraph(self):
        # Arrange
        original = {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 2, "id": "existing"}},
                {
                    "type": "taskList",
                    "content": [
                        {
                            "type": "taskItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Task"}],
                                }
                            ],
                        }
                    ],
                },
                {"type": "codeBlock", "attrs": {"id": "existing"}},
            ],
        }

        # Act
        prepared = prepare_agent_document(original)

        # Assert
        self.assertNotIn("attrs", original["content"][1])
        self.assertEqual(prepared["content"][0]["attrs"]["id"], "existing")
        ids = [
            prepared["content"][0]["attrs"]["id"],
            prepared["content"][1]["content"][0]["content"][0]["attrs"]["id"],
            prepared["content"][2]["attrs"]["id"],
            prepared["content"][3]["attrs"]["id"],
        ]
        self.assertEqual(len(set(ids)), len(ids))
        for node_id in ids[1:]:
            UUID(node_id)
        self.assertEqual(prepared["content"][-1]["type"], "paragraph")
        self.assertNotIn("content", prepared["content"][-1])
        parse_document(BLOCK_EDITOR, prepared)

    def test_existing_final_paragraph_is_preserved(self):
        # Arrange
        document = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"id": "kept"},
                    "content": [{"type": "text", "text": "Body"}],
                }
            ],
        }

        # Act
        prepared = prepare_agent_document(document)

        # Assert
        self.assertEqual(prepared, document)
        self.assertIsNot(prepared, document)

    def test_empty_document_gets_the_editors_first_paragraph(self):
        # Arrange
        document = {"type": "doc", "content": []}

        # Act
        prepared = prepare_agent_document(document)

        # Assert
        self.assertEqual(len(prepared["content"]), 1)
        self.assertEqual(prepared["content"][0]["type"], "paragraph")
        UUID(prepared["content"][0]["attrs"]["id"])
        self.assertEqual(document["content"], [])
