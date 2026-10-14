from django.test import SimpleTestCase

from researchhub_comment.constants.rh_comment_content_types import (
    QUILL_EDITOR,
    TIPTAP,
)
from researchhub_comment.models import RhCommentModel
from researchhub_comment.services.comment_html_service import render_comment_html


class RenderCommentHtmlTests(SimpleTestCase):
    def test_renders_each_node_type(self) -> None:
        """Supported nodes render as HTML; images and unsupported nodes are dropped."""
        # Arrange
        comment = RhCommentModel(
            comment_content_type=TIPTAP,
            comment_content_json={
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
            },
        )

        # Act
        html = render_comment_html(comment)

        # Assert
        self.assertEqual(
            html,
            "<h2>Results</h2>"
            '<p>Ruslan Rust<br><a href="https://example.com">Data</a></p>'
            "<hr>"
            '<a href="https://example.com/v">https://example.com/v</a>',
        )

    def test_renders_quill_text_as_escaped_paragraphs(self) -> None:
        """Quill comments render their plain text as escaped paragraphs."""
        # Arrange
        comment = RhCommentModel(
            comment_content_type=QUILL_EDITOR,
            comment_content_json={"ops": [{"insert": "Dose < 20µM"}]},
        )

        # Act
        html = render_comment_html(comment)

        # Assert
        self.assertEqual(html, "<p>Dose &lt; 20µM</p>")

    def test_renders_non_web_links_as_text(self) -> None:
        """Links without an http or https scheme render as plain text."""
        # Arrange
        comment = RhCommentModel(
            comment_content_type=TIPTAP,
            comment_content_json={
                "type": "doc",
                "content": [
                    {
                        "type": "text",
                        "text": "Data",
                        "marks": [
                            {"type": "link", "attrs": {"href": "javascript:alert(1)"}}
                        ],
                    },
                    {"type": "richLink", "attrs": {"url": "javascript:alert(1)"}},
                ],
            },
        )

        # Act
        html = render_comment_html(comment)

        # Assert
        self.assertEqual(html, "Datajavascript:alert(1)")

    def test_renders_malformed_tiptap_as_plain_text(self) -> None:
        """Tiptap content that is not a document falls back to its plain text."""
        # Arrange
        comment = RhCommentModel(
            comment_content_type=TIPTAP,
            comment_content_json=[{"type": "text", "text": "Update"}],
        )

        # Act
        html = render_comment_html(comment)

        # Assert
        self.assertEqual(html, "<p>Update</p>")

    def test_truncates_tiptap_text_across_nodes(self) -> None:
        """Text past the limit is cut with an ellipsis and later nodes are dropped."""
        # Arrange
        comment = RhCommentModel(
            comment_content_type=TIPTAP,
            comment_content_json={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Dose ",
                                "marks": [{"type": "bold"}],
                            },
                            {"type": "text", "text": "< 20µM daily"},
                        ],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Next"}],
                    },
                ],
            },
        )

        # Act
        html = render_comment_html(comment, max_length=11)

        # Assert
        self.assertEqual(html, "<p><strong>Dose </strong>&lt; 20µM...</p>")

    def test_truncates_quill_text(self) -> None:
        """Quill text past the limit is cut with an ellipsis."""
        # Arrange
        comment = RhCommentModel(
            comment_content_type=QUILL_EDITOR,
            comment_content_json={"ops": [{"insert": "Dose < 20µM daily"}]},
        )

        # Act
        html = render_comment_html(comment, max_length=8)

        # Assert
        self.assertEqual(html, "<p>Dose &lt; 2...</p>")
