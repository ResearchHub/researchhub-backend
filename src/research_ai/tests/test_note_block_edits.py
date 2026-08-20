import unittest

from research_ai.services.note_block_edits import (
    BlockEdit,
    apply_block_edits,
    check_block_edits,
    parse_block_edits,
)

BASE = ["a", "b", "c", "d"]


def _parse_and_check(raw, block_count):
    edits = parse_block_edits(raw)
    check_block_edits(edits, block_count)
    return edits


class ParseBlockEditsTests(unittest.TestCase):
    def test_parses_each_operation_kind(self):
        # Act
        edits = parse_block_edits(
            [
                {"op": "insert", "at": 2, "blocks": ["new"]},
                {"op": "replace", "from": 0, "to": 1, "blocks": ["x", "y"]},
                {"op": "delete", "from": 3, "to": 3},
            ]
        )

        # Assert
        self.assertEqual(
            edits,
            [
                BlockEdit(op="insert", at=2, blocks=["new"]),
                BlockEdit(op="replace", start=0, end=1, blocks=["x", "y"]),
                BlockEdit(op="delete", start=3, end=3),
            ],
        )

    def test_rejects_malformed_edit_arrays(self):
        # Arrange
        bad_inputs = {
            "not a list": {"op": "insert"},
            "empty list": [],
            "None": None,
            "non-dict item": ["insert"],
        }

        # Act & Assert
        for name, raw in bad_inputs.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_block_edits(raw)

    def test_rejects_bad_operations_with_indexed_messages(self):
        # Arrange
        bad_ops = {
            "unknown op": ({"op": "append"}, "op must be one of"),
            "insert with from": (
                {"op": "insert", "at": 0, "from": 1, "blocks": ["x"]},
                "insert positions with 'at'",
            ),
            "replace with at": (
                {"op": "replace", "at": 1, "from": 0, "to": 0, "blocks": ["x"]},
                "'at' belongs to insert",
            ),
            "missing at": ({"op": "insert", "blocks": ["x"]}, "'at' must be"),
            "negative index": (
                {"op": "delete", "from": -1, "to": 0},
                "'from' must be",
            ),
            "bool index": (
                {"op": "insert", "at": True, "blocks": ["x"]},
                "'at' must be",
            ),
            "to before from": (
                {"op": "delete", "from": 2, "to": 1},
                "'to' must not be less than 'from'",
            ),
            "delete with blocks": (
                {"op": "delete", "from": 0, "to": 0, "blocks": ["x"]},
                "delete takes no blocks",
            ),
            "insert without blocks": ({"op": "insert", "at": 0}, "'blocks' must be"),
            "replace with empty blocks": (
                {"op": "replace", "from": 0, "to": 0, "blocks": []},
                "'blocks' must be",
            ),
        }

        # Act & Assert: the message names the failing edit by index.
        for name, (op, message) in bad_ops.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, message) as caught:
                    parse_block_edits([{"op": "delete", "from": 9, "to": 9}, op])
                self.assertIn("edits[1]", str(caught.exception))


class CheckBlockEditsTests(unittest.TestCase):
    def test_accepts_edits_within_bounds(self):
        # Act & Assert: no exception; append position == block_count is valid.
        _parse_and_check(
            [
                {"op": "insert", "at": 4, "blocks": ["end"]},
                {"op": "replace", "from": 0, "to": 0, "blocks": ["x"]},
                {"op": "delete", "from": 2, "to": 3},
            ],
            block_count=4,
        )

    def test_rejects_out_of_range_indices(self):
        # Act & Assert
        with self.assertRaisesRegex(ValueError, "valid insert positions are 0..4"):
            _parse_and_check([{"op": "insert", "at": 5, "blocks": ["x"]}], 4)
        with self.assertRaisesRegex(ValueError, "block indices run 0..3"):
            _parse_and_check([{"op": "delete", "from": 2, "to": 4}], 4)

    def test_range_edits_on_an_empty_note_point_to_insert(self):
        # Act & Assert
        with self.assertRaisesRegex(ValueError, "no blocks to replace; use insert"):
            _parse_and_check(
                [{"op": "replace", "from": 0, "to": 0, "blocks": ["x"]}], 0
            )

    def test_rejects_overlapping_edits(self):
        # Arrange
        overlapping = {
            "range within range": [
                {"op": "replace", "from": 0, "to": 2, "blocks": ["x"]},
                {"op": "delete", "from": 1, "to": 1},
            ],
            "ranges touching": [
                {"op": "delete", "from": 0, "to": 1},
                {"op": "delete", "from": 1, "to": 2},
            ],
            "insert inside a replaced range": [
                {"op": "replace", "from": 1, "to": 3, "blocks": ["x"]},
                {"op": "insert", "at": 2, "blocks": ["y"]},
            ],
        }

        # Act & Assert
        for name, raw in overlapping.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, "overlap"):
                _parse_and_check(raw, 4)

    def test_inserts_at_range_boundaries_are_not_overlaps(self):
        # Act & Assert: before the range and right after it are unambiguous.
        _parse_and_check(
            [
                {"op": "replace", "from": 1, "to": 2, "blocks": ["x"]},
                {"op": "insert", "at": 1, "blocks": ["before"]},
                {"op": "insert", "at": 3, "blocks": ["after"]},
            ],
            block_count=4,
        )


class ApplyBlockEditsTests(unittest.TestCase):
    def test_applies_each_operation_kind(self):
        # Arrange
        cases = {
            "insert at start": (
                [{"op": "insert", "at": 0, "blocks": ["x"]}],
                ["x", *BASE],
            ),
            "append": ([{"op": "insert", "at": 4, "blocks": ["x"]}], [*BASE, "x"]),
            "replace range": (
                [{"op": "replace", "from": 1, "to": 2, "blocks": ["x", "y", "z"]}],
                ["a", "x", "y", "z", "d"],
            ),
            "delete range": ([{"op": "delete", "from": 0, "to": 2}], ["d"]),
        }

        # Act & Assert
        for name, (raw, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(
                    apply_block_edits(BASE, _parse_and_check(raw, len(BASE))), expected
                )

    def test_batched_edits_all_address_the_read_indices(self):
        # Arrange: edits listed out of positional order, every index still
        # meaning what the model read.
        raw = [
            {"op": "delete", "from": 3, "to": 3},
            {"op": "insert", "at": 1, "blocks": ["ins"]},
            {"op": "replace", "from": 1, "to": 2, "blocks": ["x", "y"]},
        ]

        # Act
        result = apply_block_edits(BASE, _parse_and_check(raw, len(BASE)))

        # Assert: insert-before-1 lands before the replacement of 1..2.
        self.assertEqual(result, ["a", "ins", "x", "y"])

    def test_same_position_inserts_keep_their_sent_order(self):
        # Arrange
        raw = [
            {"op": "insert", "at": 2, "blocks": ["first"]},
            {"op": "insert", "at": 2, "blocks": ["second"]},
        ]

        # Act
        result = apply_block_edits(BASE, _parse_and_check(raw, len(BASE)))

        # Assert
        self.assertEqual(result, ["a", "b", "first", "second", "c", "d"])

    def test_deleting_everything_yields_an_empty_list(self):
        # Act: the caller is the one that must refuse to store this.
        result = apply_block_edits(
            BASE, _parse_and_check([{"op": "delete", "from": 0, "to": 3}], len(BASE))
        )

        # Assert
        self.assertEqual(result, [])
