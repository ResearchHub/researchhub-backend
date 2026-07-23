import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest import TestCase

from utils.json import bounded_json_value, json_size_bytes


class _Unstringable:
    def __str__(self):
        raise RuntimeError("cannot stringify")


class BoundedJSONValueTests(TestCase):
    def test_converts_non_json_values_and_non_finite_floats(self):
        # Arrange
        value = {
            "bytes": b"raw",
            "date": datetime(2026, 7, 22, tzinfo=UTC),
            "decimal": Decimal("1.25"),
            "nan": float("nan"),
            "infinity": float("inf"),
        }

        # Act
        safe, is_truncated, _original_size = bounded_json_value(value, max_bytes=4096)

        # Assert
        json.dumps(safe, allow_nan=False)
        self.assertFalse(is_truncated)
        self.assertEqual(safe["decimal"], "1.25")
        self.assertEqual(safe["nan"], "nan")
        self.assertEqual(safe["infinity"], "inf")

    def test_bounds_serialized_size_and_preserves_original_size(self):
        # Arrange
        value = {"body": "x" * 4096}

        # Act
        safe, is_truncated, original_size = bounded_json_value(
            value,
            max_bytes=256,
            max_string_bytes=128,
            preview_chars=16,
        )

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(original_size, 4096)
        self.assertLessEqual(json_size_bytes(safe), 256)

    def test_bounds_collection_items(self):
        # Arrange
        value = list(range(10))

        # Act
        safe, is_truncated, _original_size = bounded_json_value(
            value,
            max_bytes=1024,
            max_collection_items=3,
        )

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(safe, [0, 1, 2, {"_truncated_items": 7}])

    def test_dict_truncation_marker_does_not_overwrite_retained_data(self):
        # Arrange
        value = {
            "_truncated_items": "user data",
            "kept": True,
            "omitted": True,
        }

        # Act
        safe, is_truncated, _original_size = bounded_json_value(
            value,
            max_bytes=1024,
            max_collection_items=2,
        )

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(safe["_truncated_items"], "user data")
        self.assertEqual(safe["__truncated_items"], 1)

    def test_bounds_cyclic_values_by_nesting_depth(self):
        # Arrange
        value = {}
        value["cycle"] = value

        # Act
        safe, is_truncated, _original_size = bounded_json_value(
            value,
            max_bytes=1024,
            max_nesting_depth=3,
        )

        # Assert
        self.assertTrue(is_truncated)
        json.dumps(safe)

    def test_marks_values_that_cannot_be_stringified(self):
        # Arrange
        value = {"broken": _Unstringable()}

        # Act
        safe, is_truncated, _original_size = bounded_json_value(
            value,
            max_bytes=1024,
        )

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(
            safe["broken"],
            {"_serialization_error": True, "type": "_Unstringable"},
        )
        json.dumps(safe)

    def test_marks_keys_that_cannot_be_stringified(self):
        # Arrange
        value = {_Unstringable(): "content"}

        # Act
        safe, is_truncated, _original_size = bounded_json_value(
            value,
            max_bytes=1024,
        )

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(safe, {"<unserializable _Unstringable>": "content"})
