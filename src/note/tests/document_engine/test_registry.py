import json
import unittest
from pathlib import Path

from note.services.document_engine.registry import (
    INVENTORY_MARKS,
    INVENTORY_NODES,
    SCHEMA_FINGERPRINT,
)

FIXTURES = Path(__file__).parent / "fixtures"


class RegistryTests(unittest.TestCase):
    def test_fixture_coverage_matches_reviewed_inventory(self):
        # Arrange
        document = json.loads((FIXTURES / "editor_document.json").read_text())
        manifest = json.loads((FIXTURES / "coverage_manifest.json").read_text())

        # Act
        node_types, mark_types, node_attributes, mark_attributes = _coverage(document)

        # Assert
        self.assertEqual(node_types, set(manifest["node_types"]))
        self.assertEqual(mark_types, set(manifest["mark_types"]))
        self.assertEqual(node_types, set(INVENTORY_NODES))
        self.assertEqual(mark_types, set(INVENTORY_MARKS))
        self.assertEqual(
            {key: sorted(value) for key, value in node_attributes.items()},
            manifest["node_attributes"],
        )
        self.assertEqual(
            {key: sorted(value) for key, value in mark_attributes.items()},
            manifest["mark_attributes"],
        )

    def test_schema_fingerprint_is_a_sha256_digest(self):
        # Arrange / Act / Assert
        self.assertEqual(len(SCHEMA_FINGERPRINT), 64)
        self.assertTrue(
            all(character in "0123456789abcdef" for character in SCHEMA_FINGERPRINT)
        )


def _coverage(
    node: dict,
) -> tuple[set[str], set[str], dict[str, set[str]], dict[str, set[str]]]:
    node_types = {node["type"]}
    mark_types = {mark["type"] for mark in node.get("marks", [])}
    node_attributes = {node["type"]: set(node["attrs"])} if node.get("attrs") else {}
    mark_attributes = {
        mark["type"]: set(mark["attrs"])
        for mark in node.get("marks", [])
        if mark.get("attrs")
    }
    for child in node.get("content", []):
        child_nodes, child_marks, child_node_attrs, child_mark_attrs = _coverage(child)
        node_types.update(child_nodes)
        mark_types.update(child_marks)
        _merge_attributes(node_attributes, child_node_attrs)
        _merge_attributes(mark_attributes, child_mark_attrs)
    return node_types, mark_types, node_attributes, mark_attributes


def _merge_attributes(target: dict[str, set[str]], source: dict[str, set[str]]):
    for type_name, attributes in source.items():
        target.setdefault(type_name, set()).update(attributes)
