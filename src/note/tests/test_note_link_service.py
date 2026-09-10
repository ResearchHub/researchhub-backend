from copy import deepcopy
from unittest import TestCase

from note.services.note_link_service import link_note_urls
from utils.prosemirror import BLOCK_EDITOR, compact_blocks, parse_blocks


class NoteLinkServiceTests(TestCase):
    def test_links_survive_editor_schema_round_trip(self):
        # Arrange
        blocks = parse_blocks(BLOCK_EDITOR, ["See https://doi.org/10.1234/paper."])

        # Act
        result = parse_blocks(BLOCK_EDITOR, link_note_urls(blocks))
        compact = compact_blocks(BLOCK_EDITOR, {"type": "doc", "content": result})

        # Assert
        linked = compact[0]["content"][1]
        self.assertEqual(linked["text"], "https://doi.org/10.1234/paper")
        self.assertEqual(
            linked["marks"],
            [{"type": "link", "attrs": {"href": "https://doi.org/10.1234/paper"}}],
        )

    def test_links_reference_urls_and_preserves_punctuation_and_marks(self):
        # Arrange
        text = "See https://doi.org/10.1234/a(b), and https://example.org/paper."
        blocks = [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": text, "marks": [{"type": "italic"}]}
                ],
            }
        ]
        original = deepcopy(blocks)

        # Act
        result = link_note_urls(blocks)

        # Assert
        nodes = result[0]["content"]
        self.assertEqual("".join(node["text"] for node in nodes), text)
        self.assertEqual(
            [
                mark["attrs"]["href"]
                for node in nodes
                for mark in node["marks"]
                if mark["type"] == "link"
            ],
            ["https://doi.org/10.1234/a(b)", "https://example.org/paper"],
        )
        self.assertTrue(all({"type": "italic"} in node["marks"] for node in nodes))
        self.assertEqual(blocks, original)

    def test_converts_markdown_reference_to_a_link_label(self):
        # Arrange
        blocks = [{"type": "text", "text": "Read [Paper](https://doi.org/a(b))."}]

        # Act
        result = link_note_urls(blocks)

        # Assert
        self.assertEqual("".join(node["text"] for node in result), "Read Paper.")
        self.assertEqual(result[1]["text"], "Paper")
        self.assertEqual(result[1]["marks"][0]["attrs"]["href"], "https://doi.org/a(b)")

    def test_preserves_existing_links_and_code(self):
        # Arrange
        blocks = [
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "https://example.org/code"}],
            },
            {
                "type": "text",
                "text": "https://example.org/inline",
                "marks": [{"type": "code"}],
            },
            {
                "type": "text",
                "text": "https://example.org/label",
                "marks": [
                    {"type": "link", "attrs": {"href": "https://example.org/target"}}
                ],
            },
        ]
        original = deepcopy(blocks)

        # Act
        result = link_note_urls(blocks)

        # Assert
        self.assertEqual(result, original)

    def test_handles_urls_in_nested_list_items(self):
        # Arrange
        blocks = [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "(https://example.org/paper).",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

        # Act
        result = link_note_urls(blocks)

        # Assert
        nodes = result[0]["content"][0]["content"][0]["content"]
        self.assertEqual(
            nodes[1]["marks"][0]["attrs"]["href"], "https://example.org/paper"
        )
        self.assertEqual(nodes[2]["text"], ").")

    def test_leaves_non_web_schemes_and_invalid_urls_unlinked(self):
        # Arrange
        blocks = [{"type": "text", "text": "javascript:alert(1) https:// https://[bad"}]

        # Act
        result = link_note_urls(blocks)

        # Assert
        self.assertEqual(result, blocks)

    def test_linking_is_idempotent(self):
        # Arrange
        blocks = [{"type": "text", "text": "https://example.org/paper."}]
        linked = link_note_urls(blocks)

        # Act
        result = link_note_urls(linked)

        # Assert
        self.assertEqual(result, linked)
