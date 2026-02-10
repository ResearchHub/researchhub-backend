from django.test import TestCase

from assistant.utils.tiptap_converter import tiptap_json_to_html


class TiptapConverterTestCase(TestCase):
    """Tests for the Tiptap JSON to HTML converter."""

    def test_empty_doc(self):
        doc = {"type": "doc", "content": []}
        self.assertEqual(tiptap_json_to_html(doc), "")

    def test_invalid_input(self):
        self.assertEqual(tiptap_json_to_html(None), "")
        self.assertEqual(tiptap_json_to_html("not json"), "")
        self.assertEqual(tiptap_json_to_html(42), "")

    def test_json_string_input(self):
        doc = '{"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]}]}'
        self.assertEqual(tiptap_json_to_html(doc), "<p>Hello</p>")

    def test_heading(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Title"}],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Subtitle"}],
                },
            ],
        }
        result = tiptap_json_to_html(doc)
        self.assertIn("<h1>Title</h1>", result)
        self.assertIn("<h2>Subtitle</h2>", result)

    def test_paragraph_with_marks(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Normal "},
                        {
                            "type": "text",
                            "marks": [{"type": "bold"}],
                            "text": "bold",
                        },
                        {"type": "text", "text": " and "},
                        {
                            "type": "text",
                            "marks": [{"type": "italic"}],
                            "text": "italic",
                        },
                    ],
                }
            ],
        }
        result = tiptap_json_to_html(doc)
        self.assertEqual(
            result, "<p>Normal <strong>bold</strong> and <em>italic</em></p>"
        )

    def test_bullet_list(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Item 1"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Item 2"}],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        result = tiptap_json_to_html(doc)
        self.assertIn("<ul>", result)
        self.assertIn("<li><p>Item 1</p></li>", result)
        self.assertIn("<li><p>Item 2</p></li>", result)

    def test_table(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableHeader",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {"type": "text", "text": "Header"}
                                            ],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {"type": "text", "text": "Cell"}
                                            ],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        result = tiptap_json_to_html(doc)
        self.assertIn("<table>", result)
        self.assertIn("<th><p>Header</p></th>", result)
        self.assertIn("<td><p>Cell</p></td>", result)

    def test_link_mark(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {
                                        "href": "https://example.com",
                                        "target": "_blank",
                                    },
                                }
                            ],
                            "text": "Click here",
                        }
                    ],
                }
            ],
        }
        result = tiptap_json_to_html(doc)
        self.assertIn('href="https://example.com"', result)
        self.assertIn("Click here</a>", result)

    def test_real_rfp_scaffold(self):
        """Test with a real Tiptap document similar to what the assistant produces."""
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [
                        {
                            "type": "text",
                            "text": "Request for Proposals - Long COVID Research",
                        }
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Summary"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "marks": [{"type": "italic"}],
                            "text": "To be drafted...",
                        }
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Background"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "marks": [{"type": "italic"}],
                            "text": "To be drafted...",
                        }
                    ],
                },
            ],
        }
        result = tiptap_json_to_html(doc)
        self.assertIn("<h1>Request for Proposals - Long COVID Research</h1>", result)
        self.assertIn("<h2>Summary</h2>", result)
        self.assertIn("<em>To be drafted...</em>", result)
        self.assertIn("<h2>Background</h2>", result)

    def test_html_escaping(self):
        """Ensure user content is HTML-escaped to prevent XSS."""
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": '<script>alert("xss")</script>'}
                    ],
                }
            ],
        }
        result = tiptap_json_to_html(doc)
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)
