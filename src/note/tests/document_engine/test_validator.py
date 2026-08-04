import copy
import json
import unittest
from pathlib import Path

from note.services.document_engine.errors import (
    DocumentSchemaMismatch,
    InvalidDocument,
    InvalidDocumentOperation,
)
from note.services.document_engine.registry import (
    EDITOR_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_DEPTH,
)
from note.services.document_engine.validator import (
    validate_created_node,
    validate_schema_version,
    validate_stored_document,
)

FIXTURES = Path(__file__).parent / "fixtures"


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((FIXTURES / "editor_document.json").read_text())

    def test_golden_document_round_trips_without_loss(self):
        # Arrange
        original = copy.deepcopy(self.document)

        # Act
        doc, changed, _warnings = validate_stored_document(self.document)

        # Assert
        self.assertFalse(changed)
        self.assertEqual(doc, original)
        self.assertEqual(self.document, original)

    def test_unknown_types_warn_and_remain_verbatim(self):
        # Arrange
        unknown = {
            "type": "futureWidget",
            "attrs": {"anything": [1, 2, 3]},
            "content": [{"type": "paragraph"}],
        }
        doc = {"type": "doc", "content": [unknown]}

        # Act
        validated, _changed, warnings = validate_stored_document(doc)

        # Assert
        self.assertEqual(validated["content"][0], unknown)
        self.assertIn("unknown_node_type", {item["code"] for item in warnings})

    def test_unprojectable_known_attribute_warns_without_mutation(self):
        # Arrange
        image = {
            "type": "imageBlock",
            "attrs": {"src": "https://example.test/a.png", "alt": {"bad": "shape"}},
        }
        doc = {"type": "doc", "content": [image]}

        # Act
        validated, _changed, warnings = validate_stored_document(doc)

        # Assert
        self.assertEqual(validated["content"][0], image)
        self.assertIn(
            "unprojectable_attribute",
            {warning["code"] for warning in warnings},
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
        first, _first_changed, first_warnings = validate_stored_document(doc)
        second, _second_changed, _second_warnings = validate_stored_document(doc)
        ids = [node["attrs"]["id"] for node in first["content"]]

        # Assert
        self.assertEqual(first, second)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "duplicate")
        self.assertEqual(
            {warning["code"] for warning in first_warnings},
            {"duplicate_node_id", "missing_node_id"},
        )

    def test_legacy_and_current_versions_are_supported(self):
        # Arrange / Act
        legacy_null = validate_schema_version(None)
        legacy_blank = validate_schema_version("")
        current = validate_schema_version(EDITOR_SCHEMA_VERSION)

        # Assert
        self.assertEqual(legacy_null, LEGACY_SCHEMA_VERSION)
        self.assertEqual(legacy_blank, LEGACY_SCHEMA_VERSION)
        self.assertEqual(current, EDITOR_SCHEMA_VERSION)

    def test_unknown_schema_version_is_rejected(self):
        # Arrange / Act / Assert
        for version in [1, {}, "future-v99"]:
            with (
                self.subTest(version=version),
                self.assertRaises(DocumentSchemaMismatch),
            ):
                validate_schema_version(version)

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
                validate_stored_document(doc)

    def test_created_attributes_are_canonicalized(self):
        # Arrange
        image = {
            "type": "imageBlock",
            "attrs": {"src": "https://example.test/new.png", "alt": "new image"},
        }

        # Act
        result = validate_created_node(image)

        # Assert
        self.assertEqual(
            result["attrs"],
            {
                "src": "https://example.test/new.png",
                "width": "100%",
                "align": "center",
                "alt": "new image",
            },
        )

    def test_invalid_created_content_is_rejected(self):
        invalid_nodes = [
            {"type": "paragraph", "attrs": {"id": "model-id"}},
            {"type": "heading", "attrs": {"level": 7}},
            {"type": "imageBlock", "attrs": {"src": "http://example.test/a.png"}},
            {"type": "paragraph", "content": [{"type": "text", "text": ""}]},
            {"type": "table", "attrs": {"id": "invented"}},
        ]
        for node in invalid_nodes:
            # Arrange / Act / Assert
            with self.subTest(node=node), self.assertRaises(InvalidDocumentOperation):
                validate_created_node(node)

    def test_malformed_created_urls_raise_typed_validation_errors(self):
        # Arrange
        invalid_nodes = [
            (
                {"type": "imageBlock", "attrs": {"src": "https://[bad"}},
                "node.attrs.src",
            ),
            (
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "linked",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {"href": "https://[bad"},
                                }
                            ],
                        }
                    ],
                },
                "node.content[0].marks[0].attrs.href",
            ),
        ]
        for node, expected_path in invalid_nodes:
            with self.subTest(node=node):
                # Act
                with self.assertRaises(InvalidDocumentOperation) as context:
                    validate_created_node(node)

                # Assert
                self.assertEqual(context.exception.path, expected_path)

    def test_generated_ids_cannot_push_document_past_size_limit(self):
        # Arrange
        padding = ["x" * 990_000 for _ in range(5)]
        doc = {
            "type": "doc",
            "content": [
                *({"type": "paragraph"} for _ in range(1_000)),
                {"type": "futureWidget", "attrs": {"padding": padding}},
            ],
        }
        input_size = len(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        self.assertLess(input_size, MAX_DOCUMENT_BYTES)

        # Act
        with self.assertRaises(InvalidDocument) as context:
            validate_stored_document(doc)

        # Assert
        self.assertEqual(context.exception.path, "doc")
        self.assertIn("maximum size", str(context.exception))

    def test_mark_attributes_share_the_document_depth_limit(self):
        # Arrange
        node = {
            "type": "text",
            "text": "deeply marked",
            "marks": [{"type": "futureMark", "attrs": {"value": "ok"}}],
        }
        for _ in range(MAX_DOCUMENT_DEPTH - 1):
            node = {"type": "paragraph", "content": [node]}
        doc = {"type": "doc", "content": [node]}

        # Act
        with self.assertRaises(InvalidDocument) as context:
            validate_stored_document(doc)

        # Assert
        self.assertIn("maximum depth", str(context.exception))
        self.assertTrue(context.exception.path.endswith(".marks[0].attrs"))

    def test_encoding_failures_are_typed_validation_errors(self):
        # Arrange
        invalid_text = "\ud800"
        cases = [
            (
                "stored",
                lambda: validate_stored_document(
                    {
                        "type": "doc",
                        "content": [{"type": "text", "text": invalid_text}],
                    }
                ),
                InvalidDocument,
            ),
            (
                "created",
                lambda: validate_created_node(
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": invalid_text}],
                    }
                ),
                InvalidDocumentOperation,
            ),
        ]

        for name, validate, error_type in cases:
            # Act / Assert
            with self.subTest(name=name), self.assertRaises(error_type):
                validate()
