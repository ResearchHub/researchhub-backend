import json
import unittest

from research_ai.services.notebook_chat.draft_markdown import (
    MAX_INPUT_BYTES,
    ToolDraftMarkdown,
)


class ToolDraftMarkdownTests(unittest.TestCase):
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
        draft = ToolDraftMarkdown()
        # Act
        for char in payload:
            draft.feed(char)
            draft.snapshot()
        # Assert
        self.assertEqual(
            draft.snapshot(), "## Overview\n\nA paragraph\\.\n\n- First item"
        )

    def test_unfinished_paragraph_streams_before_json_closes(self):
        # Arrange
        draft = ToolDraftMarkdown()
        # Act
        draft.feed('{"edits":[{"blocks":["Already writing')
        # Assert
        self.assertEqual(draft.snapshot(), "Already writing")

    def test_preserves_inline_text_and_marks_without_artificial_paragraphs(self):
        # Arrange
        draft = ToolDraftMarkdown()
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
        self.assertEqual(draft.snapshot(), "Some **bold** text")

    def test_ignores_arguments_and_unsafe_links_and_escapes_markdown(self):
        # Arrange
        draft = ToolDraftMarkdown()
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
        self.assertEqual(draft.snapshot(), r"\[click\]\(bad\)")

    def test_unicode_survives_fragment_boundaries(self):
        # Arrange
        payload = json.dumps({"edits": [{"blocks": ["Café 🌱"]}]})
        draft = ToolDraftMarkdown()
        # Act
        for char in payload:
            draft.feed(char)
            draft.snapshot()
        # Assert
        self.assertEqual(draft.snapshot(), "Café 🌱")

    def test_preview_input_is_bounded(self):
        # Arrange
        draft = ToolDraftMarkdown()
        # Act
        draft.feed("x" * (MAX_INPUT_BYTES + 100))
        draft.feed("x" * 100)
        # Assert
        self.assertEqual(len(draft._input), MAX_INPUT_BYTES)
        self.assertEqual(draft.snapshot(), "")
