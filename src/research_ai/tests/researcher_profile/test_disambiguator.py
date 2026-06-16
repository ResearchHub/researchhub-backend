"""Unit tests for researcher_profile.disambiguator (LLM author disambiguation)."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import disambiguator
from research_ai.tests.researcher_profile.helpers import make_expert
from utils.tests.openalex_helpers import create_oa_author_record


def _scored():
    return [
        (1.0, create_oa_author_record(id="https://openalex.org/A1")),
        (1.0, create_oa_author_record(id="https://openalex.org/A2")),
    ]


class DisambiguateAuthorTests(SimpleTestCase):
    def test_picks_candidate_by_index(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": 1, "confidence": 0.9, "reasoning": "affiliation matches"}'
        )
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertTrue(result.chosen)
        self.assertEqual(result.record["id"], "https://openalex.org/A2")
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.name_score, 1.0)

    def test_abstain_when_choice_is_null(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "confidence": 0.1, "reasoning": "x"}'
        )
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertFalse(result.chosen)
        self.assertIsNone(result.record)

    def test_out_of_range_choice_coerced_to_abstain(self):
        # Arrange: a malformed index must never select a wrong author.
        llm = MagicMock()
        llm.invoke.return_value = '{"choice": 7, "confidence": 0.9, "reasoning": "x"}'
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertFalse(result.chosen)

    def test_boolean_choice_coerced_to_abstain(self):
        # Arrange: JSON booleans are ints in Python, but not valid candidate ids.
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": false, "confidence": 0.9, "reasoning": "abstain"}'
        )
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertFalse(result.chosen)
        self.assertIsNone(result.record)

    def test_handles_json_code_fences(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.return_value = (
            '```json\n{"choice": 0, "confidence": 0.8, "reasoning": "x"}\n```'
        )
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertTrue(result.chosen)
        self.assertEqual(result.record["id"], "https://openalex.org/A1")

    def test_clamps_model_confidence_to_valid_range(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": 0, "confidence": 1.7, "reasoning": "overconfident"}'
        )
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertEqual(result.confidence, 1.0)

    def test_llm_error_returns_abstain_with_error(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("llm down")
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertFalse(result.chosen)
        self.assertIn("llm down", result.error or "")

    def test_unparseable_reply_returns_abstain(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.return_value = "I think it is the second one."
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert
        self.assertFalse(result.chosen)
        self.assertIsNotNone(result.error)

    def test_reports_found_identifier_instead_of_a_candidate(self):
        # Arrange: none of the candidates fit, but web search found an ORCID.
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "orcid": "0000-0002-1825-0097", '
            '"openalex_id": null, "confidence": 0.8, "reasoning": "moved"}'
        )
        # Act
        result = disambiguator.disambiguate_author(make_expert(), _scored(), llm=llm)
        # Assert: not "chosen" (no candidate record), but carries the id to verify.
        self.assertFalse(result.chosen)
        self.assertEqual(result.found_orcid, "0000-0002-1825-0097")
        self.assertIsNone(result.found_openalex_id)

    def test_empty_candidates_still_invokes_llm(self):
        # Arrange: no candidates -> the model is still asked to look the expert up.
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "openalex_id": "https://openalex.org/A9", '
            '"confidence": 0.7, "reasoning": "found"}'
        )
        # Act
        result = disambiguator.disambiguate_author(make_expert(), [], llm=llm)
        # Assert
        llm.invoke.assert_called_once()
        self.assertFalse(result.chosen)
        self.assertEqual(result.found_openalex_id, "https://openalex.org/A9")
