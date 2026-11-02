import tempfile
from pathlib import Path
from unittest import TestCase

from research_ai.evals.cases import (
    ASSISTANT,
    NOTEBOOK,
    CaseError,
    load_case,
    load_cases,
    parse_case,
)


def _notebook_case(**overrides):
    raw = {
        "id": "notebook/example",
        "agent": NOTEBOOK,
        "note": {"title": "T", "blocks": ["## Methods", "Text"]},
        "turns": ["Do something."],
    }
    raw.update(overrides)
    return raw


class ParseCaseTests(TestCase):
    def test_expands_heading_shorthand_and_keeps_other_blocks(self):
        # Act
        case = parse_case(_notebook_case())

        # Assert
        self.assertEqual(
            case.note.blocks,
            [
                {"type": "heading", "attrs": {"level": 2}, "content": ["Methods"]},
                "Text",
            ],
        )

    def test_defaults_expectations(self):
        # Act
        case = parse_case(_notebook_case())

        # Assert
        self.assertEqual(case.expect.tools_called, [])
        self.assertFalse(case.expect.note_unchanged)

    def test_rejects_unknown_expect_keys(self):
        # Arrange
        raw = _notebook_case(expect={"tool_called": ["read_note"]})

        # Act / Assert
        with self.assertRaisesRegex(CaseError, "unknown expect keys"):
            parse_case(raw)

    def test_rejects_malformed_case_fields(self):
        cases = [
            ("not a mapping", "must be a mapping"),
            (_notebook_case(id=""), "id must be"),
            (_notebook_case(turns=[]), "turns must be"),
            (_notebook_case(turns=["  "]), "turns must be"),
            (_notebook_case(note=["x"]), "note must be a mapping"),
            (_notebook_case(note={"title": "T", "blocks": []}), "note.blocks"),
            (_notebook_case(expect=["x"]), "expect must be a mapping"),
            (_notebook_case(expect={"tools_called": "read_note"}), "list of strings"),
            (_notebook_case(expect={"min_new_dois": 0}), "positive integer"),
            (_notebook_case(expect={"doi_section": "Refs"}), "needs min_new_dois"),
            (
                _notebook_case(expect={"min_new_dois": 1, "doi_section": ""}),
                "must be a heading",
            ),
        ]
        for raw, message in cases:
            # Act / Assert
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(CaseError, message),
            ):
                parse_case(raw)

    def test_load_case_names_the_file_on_invalid_yaml(self):
        # Arrange
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "broken.yaml"
            path.write_text("id: [unclosed", encoding="utf-8")

            # Act / Assert
            with self.assertRaisesRegex(CaseError, "broken.yaml"):
                load_case(path)

    def test_rejects_a_non_boolean_flag(self):
        # Arrange
        raw = _notebook_case(expect={"note_unchanged": "yes"})

        # Act / Assert
        with self.assertRaisesRegex(CaseError, "note_unchanged must be true or false"):
            parse_case(raw)

    def test_rejects_a_reply_limit_that_is_not_a_positive_integer(self):
        for value in (True, 0, "2000"):
            with self.subTest(value=value):
                # Arrange
                raw = _notebook_case(expect={"max_reply_chars": value})

                # Act / Assert
                with self.assertRaisesRegex(CaseError, "positive integer"):
                    parse_case(raw)

    def test_notebook_case_needs_a_note(self):
        # Arrange
        raw = _notebook_case(note=None)

        # Act / Assert
        with self.assertRaisesRegex(CaseError, "needs a note"):
            parse_case(raw)

    def test_assistant_case_starts_without_a_note(self):
        # Arrange
        raw = _notebook_case(agent=ASSISTANT)

        # Act / Assert
        with self.assertRaisesRegex(CaseError, "starts with no note"):
            parse_case(raw)

    def test_rejects_unknown_document_type(self):
        # Arrange
        raw = _notebook_case(
            note={"title": "T", "document_type": "PAPER", "blocks": ["x"]}
        )

        # Act / Assert
        with self.assertRaisesRegex(CaseError, "document_type"):
            parse_case(raw)


class CheckedInCasesTests(TestCase):
    def test_every_checked_in_case_parses_with_a_unique_id(self):
        # Act
        cases = load_cases()

        # Assert
        ids = [case.id for case in cases]
        self.assertTrue(cases)
        self.assertEqual(len(ids), len(set(ids)))

    def test_filters_by_agent_and_id_pattern(self):
        # Act
        notebook = load_cases(agent=NOTEBOOK)
        matched = load_cases(pattern="assistant/*")

        # Assert
        self.assertTrue(all(case.agent == NOTEBOOK for case in notebook))
        self.assertTrue(all(case.id.startswith("assistant/") for case in matched))
        self.assertTrue(matched)
