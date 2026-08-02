from unittest import TestCase

from note.services.note_blocks import (
    NoteBlockError,
    RenderedBlock,
    build_nodes,
    derive_plain_text,
    parse_inline,
    render_blocks,
    render_inline,
)


class NoteBlocksTests(TestCase):
    def test_inline_grammar_round_trips_clean_text(self):
        # Arrange
        text = "Plain **bold** *italic* `code` and [a link](https://example.com)."

        # Act
        rendered = render_inline(parse_inline(text))

        # Assert
        self.assertEqual(rendered, text)

    def test_parse_inline_preserves_malformed_syntax_as_literal_text(self):
        # Arrange
        malformed = "An **open bold and [broken](link"

        # Act
        nodes = parse_inline(malformed)

        # Assert
        self.assertEqual(nodes, [{"type": "text", "text": malformed}])
        self.assertEqual(render_inline(nodes), malformed)

    def test_render_inline_ignores_unknown_marks(self):
        # Arrange
        nodes = [
            {
                "type": "text",
                "text": "highlighted",
                "marks": [{"type": "highlight", "attrs": {"color": "yellow"}}],
            }
        ]

        # Act
        rendered = render_inline(nodes)

        # Assert
        self.assertEqual(rendered, "highlighted")

    def test_render_blocks_returns_indexed_typed_blocks(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Methods"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Important",
                            "marks": [{"type": "bold"}],
                        }
                    ],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "First"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Second"}],
                                }
                            ],
                        },
                    ],
                },
                {
                    "type": "orderedList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Only"}],
                                }
                            ],
                        }
                    ],
                },
            ],
        }

        # Act
        blocks = render_blocks(doc)

        # Assert
        self.assertEqual(
            blocks,
            [
                RenderedBlock(0, "heading", "Methods", True, 2),
                RenderedBlock(1, "paragraph", "**Important**", True),
                RenderedBlock(2, "bullet_list", "- First\n- Second", True),
                RenderedBlock(3, "ordered_list", "1. Only", True),
            ],
        )

    def test_render_blocks_flags_unsupported_nodes_with_extractable_text(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {"type": "image", "attrs": {"src": "image.png"}},
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {"type": "text", "text": "Cell text"}
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ],
        }

        # Act
        blocks = render_blocks(doc)

        # Assert
        self.assertEqual(blocks[0].content, "[image]")
        self.assertFalse(blocks[0].supported)
        self.assertEqual(blocks[1].content, "[table] Cell text")
        self.assertFalse(blocks[1].supported)

    def test_build_nodes_matches_editor_shapes(self):
        # Arrange
        blocks = [
            {"type": "heading", "level": 2, "text": "**Methods**"},
            {"type": "paragraph", "text": "Read [this](https://example.com)."},
            {"type": "bullet_list", "items": ["One", "*Two*"]},
            {"type": "ordered_list", "items": ["`First`"]},
        ]

        # Act
        nodes = build_nodes(blocks)

        # Assert
        self.assertEqual(
            nodes,
            [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [
                        {
                            "type": "text",
                            "text": "Methods",
                            "marks": [{"type": "bold"}],
                        }
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Read "},
                        {
                            "type": "text",
                            "text": "this",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {"href": "https://example.com"},
                                }
                            ],
                        },
                        {"type": "text", "text": "."},
                    ],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "One"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Two",
                                            "marks": [{"type": "italic"}],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                },
                {
                    "type": "orderedList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "First",
                                            "marks": [{"type": "code"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ],
        )

    def test_build_nodes_reports_model_correctable_errors(self):
        # Arrange
        invalid_blocks = [
            ([{"type": "quote", "text": "No"}], "unsupported type"),
            ([{"type": "heading", "level": 7, "text": "No"}], "1 to 6"),
            ([{"type": "paragraph"}], "include a text string"),
            ([{"type": "bullet_list", "items": "No"}], "list of strings"),
        ]

        # Act / Assert
        for blocks, message in invalid_blocks:
            with (
                self.subTest(blocks=blocks),
                self.assertRaisesRegex(NoteBlockError, message),
            ):
                build_nodes(blocks)

    def test_derive_plain_text_includes_unsupported_blocks(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "content": [{"type": "text", "text": "Title"}],
                },
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [{"type": "text", "text": "Unknown content"}],
                        }
                    ],
                },
            ],
        }

        # Act
        plain_text = derive_plain_text(doc)

        # Assert
        self.assertEqual(plain_text, "Title\n\nUnknown content")
