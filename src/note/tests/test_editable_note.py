from unittest import TestCase

from note.services.editable_note import (
    UnsupportedEditableNoteError,
    require_editable_note,
)


class EditableNoteTests(TestCase):
    def test_accepts_editable_heading_and_body_document(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 1}},
                {"type": "paragraph"},
            ],
        }

        # Act
        result = require_editable_note(doc)

        # Assert
        self.assertIs(result, doc)

    def test_rejects_legacy_and_incomplete_documents(self):
        # Arrange
        invalid_docs = [
            None,
            {},
            {"type": "doc", "content": []},
            {"type": "doc", "content": [{"type": "heading"}]},
            {
                "type": "doc",
                "content": [{"type": "paragraph"}, {"type": "paragraph"}],
            },
        ]

        # Act / Assert
        for doc in invalid_docs:
            with self.subTest(doc=doc), self.assertRaises(UnsupportedEditableNoteError):
                require_editable_note(doc)
