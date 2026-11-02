from unittest import TestCase

from research_ai.evals.cases import (
    ASSISTANT,
    NOTEBOOK,
    CaseError,
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
        # Act / Assert
        with self.assertRaisesRegex(CaseError, "unknown expect keys"):
            parse_case(_notebook_case(expect={"tool_called": ["read_note"]}))

    def test_notebook_case_needs_a_note(self):
        # Act / Assert
        with self.assertRaisesRegex(CaseError, "needs a note"):
            parse_case(_notebook_case(note=None))

    def test_assistant_case_starts_without_a_note(self):
        # Act / Assert
        with self.assertRaisesRegex(CaseError, "starts with no note"):
            parse_case(_notebook_case(agent=ASSISTANT))

    def test_rejects_unknown_document_type(self):
        # Act / Assert
        with self.assertRaisesRegex(CaseError, "document_type"):
            parse_case(
                _notebook_case(
                    note={"title": "T", "document_type": "PAPER", "blocks": ["x"]}
                )
            )


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
