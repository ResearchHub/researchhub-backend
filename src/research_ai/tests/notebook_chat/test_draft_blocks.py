import json
import unittest

from research_ai.services.notebook_chat.draft_blocks import (
    MAX_INPUT_BYTES,
    ToolDraftBlocks,
)
from utils.prosemirror import expand_blocks


class ToolDraftBlocksTests(unittest.TestCase):
    def test_heading_and_list_structure_survives_every_fragment(self):
        # Arrange: the heading's type/attrs arrive after its text.
        payload = json.dumps(
            {
                "edits": [
                    {
                        "blocks": [
                            {
                                "content": [{"type": "text", "text": "Overview"}],
                                "attrs": {"level": 2},
                                "type": "heading",
                            },
                            "A paragraph.",
                            {
                                "type": "bulletList",
                                "content": [
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": ["First item"],
                                            }
                                        ],
                                    }
                                ],
                            },
                        ]
                    }
                ]
            }
        )
        draft = ToolDraftBlocks()
        # Act
        for char in payload:
            draft.feed(char)
            draft.snapshot()
        # Assert
        self.assertEqual(
            draft.snapshot(), expand_blocks(json.loads(payload)["edits"][0]["blocks"])
        )

    def test_unfinished_paragraph_streams_before_json_closes(self):
        # Arrange
        draft = ToolDraftBlocks()
        # Act
        draft.feed('{"edits":[{"blocks":["Already writing')
        # Assert
        self.assertEqual(draft.snapshot(), expand_blocks(["Already writing"]))

    def test_preserves_inline_text_and_marks_without_artificial_paragraphs(self):
        # Arrange
        draft = ToolDraftBlocks()
        # Act
        draft.feed(
            json.dumps(
                {
                    "edits": [
                        {
                            "blocks": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        "Some ",
                                        {
                                            "type": "text",
                                            "text": "bold",
                                            "marks": [{"type": "bold"}],
                                        },
                                        " text",
                                    ],
                                }
                            ]
                        }
                    ]
                }
            )
        )
        # Assert
        self.assertEqual(
            draft.snapshot()[0]["content"],
            [
                {"type": "text", "text": "Some "},
                {"type": "text", "text": "bold", "marks": [{"type": "bold"}]},
                {"type": "text", "text": " text"},
            ],
        )

    def test_streams_only_note_blocks_without_interpreting_their_content(self):
        # Arrange
        draft = ToolDraftBlocks()
        # Act
        text = {
            "type": "text",
            "text": "[click](bad)",
            "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
        }
        draft.feed(
            json.dumps(
                {
                    "note_id": 12,
                    "secret": "not content",
                    "edits": [
                        {
                            "op": "insert",
                            "blocks": [{"type": "paragraph", "content": [text]}],
                        }
                    ],
                }
            )
        )
        # Assert
        self.assertEqual(draft.snapshot(), [{"type": "paragraph", "content": [text]}])

    def test_unicode_survives_fragment_boundaries(self):
        # Arrange
        payload = json.dumps({"edits": [{"blocks": ["Café 🌱"]}]})
        draft = ToolDraftBlocks()
        # Act
        for char in payload:
            draft.feed(char)
            draft.snapshot()
        # Assert
        self.assertEqual(draft.snapshot(), expand_blocks(["Café 🌱"]))

    def test_preview_input_is_bounded(self):
        # Arrange
        draft = ToolDraftBlocks()
        # Act
        draft.feed("x" * (MAX_INPUT_BYTES + 100))
        draft.feed("x" * 100)
        # Assert
        self.assertEqual(len(draft._input), MAX_INPUT_BYTES)
        self.assertEqual(draft.snapshot(), [])

    def test_malformed_fragment_retains_last_snapshot(self):
        # Arrange
        draft = ToolDraftBlocks()
        draft.feed('{"edits":[{"blocks":["Visible text"]}]}')
        previous = draft.snapshot()
        # Act
        draft.feed("not json")
        # Assert
        self.assertEqual(draft.snapshot(), previous)

    def test_expanded_snapshot_is_bounded(self):
        # Arrange: tiny compact strings expand into larger node dictionaries.
        draft = ToolDraftBlocks()
        # Act
        draft.feed(json.dumps({"edits": [{"blocks": ["a"] * 5000}]}))
        # Assert
        self.assertEqual(draft.snapshot(), [])
