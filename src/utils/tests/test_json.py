from unittest import TestCase

from utils.json import bounded_json_value, json_size_bytes


class BoundedJSONValueTests(TestCase):
    def test_keeps_native_json_within_limit(self):
        # Arrange
        value = {"enabled": True, "items": [1, "two", None]}

        # Act
        safe, was_replaced, original_size = bounded_json_value(
            value,
            max_bytes=1024,
        )

        # Assert
        self.assertFalse(was_replaced)
        self.assertEqual(safe, value)
        self.assertEqual(original_size, json_size_bytes(value))

    def test_replaces_non_json_value_with_error_marker(self):
        # Arrange
        value = {"raw": b"not json"}

        # Act
        safe, was_replaced, original_size = bounded_json_value(
            value,
            max_bytes=1024,
        )

        # Assert
        self.assertTrue(was_replaced)
        self.assertTrue(safe["_serialization_error"])
        self.assertEqual(safe["error"], "TypeError")
        self.assertEqual(original_size, 0)

    def test_replaces_non_finite_float_with_error_marker(self):
        # Arrange
        value = {"score": float("nan")}

        # Act
        safe, was_replaced, original_size = bounded_json_value(
            value,
            max_bytes=1024,
        )

        # Assert
        self.assertTrue(was_replaced)
        self.assertTrue(safe["_serialization_error"])
        self.assertEqual(safe["error"], "ValueError")
        self.assertEqual(original_size, 0)

    def test_replaces_oversized_json_and_reports_encoded_size(self):
        # Arrange
        value = {"body": "x" * 4096}

        # Act
        safe, was_replaced, original_size = bounded_json_value(
            value,
            max_bytes=256,
            preview_chars=16,
        )

        # Assert
        self.assertTrue(was_replaced)
        self.assertEqual(original_size, json_size_bytes(value))
        self.assertEqual(safe["original_size_bytes"], original_size)
        self.assertLessEqual(json_size_bytes(safe), 256)

    def test_replaces_cyclic_value_with_error_marker(self):
        # Arrange
        value = {}
        value["cycle"] = value

        # Act
        safe, was_replaced, original_size = bounded_json_value(
            value,
            max_bytes=1024,
        )

        # Assert
        self.assertTrue(was_replaced)
        self.assertTrue(safe["_serialization_error"])
        self.assertEqual(original_size, 0)

    def test_replaces_value_when_json_round_trip_changes_keys(self):
        # Arrange
        value = {1: "integer key", "1": "string key"}

        # Act
        safe, was_replaced, _original_size = bounded_json_value(
            value,
            max_bytes=1024,
        )

        # Assert
        self.assertTrue(was_replaced)
        self.assertTrue(safe["_serialization_error"])

    def test_rejects_non_positive_max_bytes(self):
        # Arrange
        value = {}

        # Act / Assert
        with self.assertRaisesRegex(ValueError, "positive integers"):
            bounded_json_value(value, max_bytes=0)
