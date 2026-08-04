import copy
import json
import unittest
from pathlib import Path

from note.services.document_engine import (
    EDITOR_SCHEMA_VERSION,
    DocumentSchemaMismatch,
    InvalidDocument,
    NoteDocumentEngine,
)

FIXTURES = Path(__file__).parent / "fixtures"


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.engine = NoteDocumentEngine()
        self.document = json.loads((FIXTURES / "editor_document.json").read_text())

    def test_golden_document_round_trips_without_loss(self):
        # Arrange
        original = copy.deepcopy(self.document)

        # Act
        result = self.engine.validate({"doc": self.document})

        # Assert
        self.assertTrue(result["valid"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["doc"], original)
        self.assertEqual(result["schema_version"], EDITOR_SCHEMA_VERSION)
        self.assertEqual(self.document, original)

    def test_plain_text_covers_all_text_leaves_and_projected_attributes(self):
        # Arrange
        expected_text = _text_leaves(self.document)

        # Act
        plain_text = self.engine.validate({"doc": self.document})["plain_text"]

        # Assert
        for value in expected_text:
            self.assertIn(value, plain_text)
        self.assertIn("image-alt-token", plain_text)
        self.assertIn("microscope", plain_text)
        self.assertIn("https://www.youtube.com/watch?v=example", plain_text)
        self.assertIn("table-header-token\ttable-cell-token", plain_text)
        self.assertIn("  indented = True\n", plain_text)

    def test_unknown_types_warn_and_remain_verbatim(self):
        # Arrange
        unknown = {"type": "futureWidget", "attrs": {"anything": [1, 2, 3]}}
        doc = {"type": "doc", "content": [unknown]}

        # Act
        result = self.engine.validate({"doc": doc})

        # Assert
        self.assertEqual(result["doc"]["content"][0], unknown)
        self.assertIn(
            "unknown_node_type", {item["code"] for item in result["warnings"]}
        )

    def test_unprojectable_known_attribute_warns_without_mutation(self):
        # Arrange
        image = {
            "type": "imageBlock",
            "attrs": {"src": "https://example.test/a.png", "alt": {"bad": "shape"}},
        }
        doc = {"type": "doc", "content": [image]}

        # Act
        result = self.engine.validate({"doc": doc})

        # Assert
        self.assertEqual(result["doc"]["content"][0], image)
        self.assertIn(
            "unprojectable_attribute",
            {warning["code"] for warning in result["warnings"]},
        )

    def test_missing_and_duplicate_ids_are_repaired_deterministically(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "attrs": {"id": "duplicate"}},
                {"type": "heading", "attrs": {"id": "duplicate", "level": 1}},
                {"type": "codeBlock", "attrs": {"language": None}},
            ],
        }

        # Act
        first = self.engine.validate({"doc": doc})
        second = self.engine.validate({"doc": doc})
        ids = [node["attrs"]["id"] for node in first["doc"]["content"]]

        # Assert
        self.assertEqual(first["doc"], second["doc"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "duplicate")
        self.assertEqual(
            {warning["code"] for warning in first["warnings"]},
            {"duplicate_node_id", "missing_node_id"},
        )

    def test_legacy_and_current_versions_are_supported(self):
        # Arrange / Act
        legacy = self.engine.validate({"schema_version": None, "doc": self.document})
        current = self.engine.validate(
            {"schema_version": EDITOR_SCHEMA_VERSION, "doc": self.document}
        )

        # Assert
        self.assertEqual(legacy["doc"], current["doc"])

    def test_unknown_schema_version_is_rejected(self):
        # Arrange / Act / Assert
        for version in ["", 1, {}, "future-v99"]:
            with (
                self.subTest(version=version),
                self.assertRaises(DocumentSchemaMismatch),
            ):
                self.engine.validate({"schema_version": version, "doc": self.document})

    def test_malformed_document_is_rejected(self):
        malformed_documents = [
            None,
            {},
            {"type": "not-doc", "content": []},
            {"type": "doc"},
            {"type": "doc", "content": "not-an-array"},
            {"type": "doc", "content": None},
            {"type": "doc", "content": [], "attrs": None},
            {"type": "doc", "content": [{"type": "text", "text": ""}]},
            {
                "type": "doc",
                "content": [{"type": "text", "text": "valid", "marks": None}],
            },
            {"type": "doc", "content": [{"type": "paragraph", "extra": True}]},
        ]
        for doc in malformed_documents:
            # Arrange / Act / Assert
            with self.subTest(doc=doc), self.assertRaises(InvalidDocument):
                self.engine.validate({"doc": doc})


def _text_leaves(node: dict) -> list[str]:
    values = [node["text"]] if node["type"] == "text" else []
    for child in node.get("content", []):
        values.extend(_text_leaves(child))
    return values
