from unittest import TestCase

from researchhub_comment.services.comment_html_service import render_comment_html


class RenderCommentHtmlTests(TestCase):
    def test_renders_each_node_type(self) -> None:
        """Every supported node renders as HTML and unsupported nodes are dropped."""
        # Arrange
        document = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Results"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "mention", "attrs": {"label": "Ruslan Rust"}},
                        {"type": "hardBreak"},
                        {
                            "type": "text",
                            "text": "Data",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {"href": "https://example.com"},
                                }
                            ],
                        },
                    ],
                },
                {"type": "horizontalRule"},
                {"type": "image", "attrs": {"src": "https://example.com/a.png"}},
                {"type": "richLink", "attrs": {"url": "https://example.com/v"}},
                {"type": "sectionHeader"},
            ],
        }

        # Act
        html = render_comment_html(document)

        # Assert
        self.assertEqual(
            html,
            "<h2>Results</h2>"
            '<p>Ruslan Rust<br><a href="https://example.com">Data</a></p>'
            "<hr>"
            '<img src="https://example.com/a.png" alt="">'
            '<a href="https://example.com/v">https://example.com/v</a>',
        )
