from django.test import SimpleTestCase

from researchhub_comment.constants.rh_comment_content_types import (  # noqa: E501
    QUILL_EDITOR,
    TIPTAP,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel


class RhCommentModelPlainTextTest(SimpleTestCase):
    """Unit tests for the :pyattr:`RhCommentModel.plain_text` property."""

    def _make_comment(self, *, content_json, content_type):
        """Return an *unsaved* :class:`RhCommentModel` instance for tests."""
        return RhCommentModel(
            comment_content_json=content_json,
            comment_content_type=content_type,
            # Unused fields – set to ``None`` so we can instantiate without DB.
            thread=None,
            created_by=None,
        )

    def test_plain_text_quill(self):
        quill_json = {"ops": [{"insert": "Hello "}, {"insert": "world!"}]}
        comment = self._make_comment(content_json=quill_json, content_type=QUILL_EDITOR)
        self.assertEqual(comment.plain_text, "Hello world!")

    def test_plain_text_tiptap(self):
        tiptap_json = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "world!"},
                    ],
                }
            ],
        }
        comment = self._make_comment(content_json=tiptap_json, content_type=TIPTAP)
        self.assertEqual(comment.plain_text, "Hello world!")
