import json
import unittest
from pathlib import Path

from note.services.document_engine import InvalidDocumentOperation, NoteDocumentEngine

FIXTURES = Path(__file__).parent / "fixtures"


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.engine = NoteDocumentEngine()
        self.document = json.loads((FIXTURES / "editor_document.json").read_text())

    def test_read_is_bounded_and_lossless(self):
        # Arrange
        expected = self.document["content"][1:3]

        # Act
        result = self.engine.read({"doc": self.document, "from": 1, "limit": 2})

        # Assert
        self.assertEqual(result["doc"]["content"], expected)
        self.assertEqual([block["node"] for block in result["blocks"]], expected)
        self.assertEqual(result["returned"], 2)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_from"], 3)

    def test_read_exposes_stable_and_index_locators(self):
        # Arrange / Act
        result = self.engine.read({"doc": self.document})
        blocks = {block["node"]["type"]: block for block in result["blocks"]}

        # Assert
        self.assertEqual(blocks["heading"]["locator"], "heading-1")
        self.assertEqual(blocks["horizontalRule"]["locator"], "i:3")
        self.assertIn("replace", blocks["heading"]["capabilities"])
        self.assertNotIn("replace", blocks["table"]["capabilities"])
        self.assertEqual(
            blocks["table"]["capabilities"], ["insert_after", "move", "delete"]
        )

    def test_read_rejects_invalid_bounds(self):
        for start, limit in [(-1, 1), (0, 0), (0, 101), (True, 1)]:
            # Arrange / Act / Assert
            with (
                self.subTest(start=start, limit=limit),
                self.assertRaises(InvalidDocumentOperation),
            ):
                self.engine.read({"doc": self.document, "from": start, "limit": limit})
