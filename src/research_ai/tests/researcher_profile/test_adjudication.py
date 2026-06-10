"""Unit tests for researcher_profile.adjudication."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import adjudication
from research_ai.tests.researcher_profile.helpers import make_expert, oa_author_record


def _records():
    return [
        oa_author_record(id="https://openalex.org/A1"),
        oa_author_record(id="https://openalex.org/A2"),
    ]


class PickCandidateTests(SimpleTestCase):
    def test_picks_confident_candidate(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"candidate_index": 1, "confidence": 0.92, "reason": "match"}'
        )
        # Act
        record, confidence = adjudication.pick_candidate(
            make_expert(), _records(), service=llm
        )
        # Assert
        self.assertEqual(record["id"], "https://openalex.org/A2")
        self.assertEqual(confidence, 0.92)

    def test_null_index_or_low_confidence_picks_nothing(self):
        # Arrange
        llm = MagicMock()
        expert = make_expert()
        # Act / Assert: explicit decline.
        llm.invoke.return_value = (
            '{"candidate_index": null, "confidence": 0.9, "reason": "unsure"}'
        )
        self.assertEqual(
            adjudication.pick_candidate(expert, _records(), service=llm), (None, 0.0)
        )
        # Act / Assert: confident-sounding pick below the threshold.
        llm.invoke.return_value = (
            '{"candidate_index": 0, "confidence": 0.5, "reason": "maybe"}'
        )
        self.assertEqual(
            adjudication.pick_candidate(expert, _records(), service=llm), (None, 0.0)
        )

    def test_invalid_or_out_of_range_output_picks_nothing(self):
        # Arrange
        llm = MagicMock()
        expert = make_expert()
        # Act / Assert: unparseable output.
        llm.invoke.return_value = "I think it is candidate 1."
        self.assertEqual(
            adjudication.pick_candidate(expert, _records(), service=llm), (None, 0.0)
        )
        # Act / Assert: index outside the candidate list.
        llm.invoke.return_value = (
            '{"candidate_index": 7, "confidence": 0.95, "reason": "match"}'
        )
        self.assertEqual(
            adjudication.pick_candidate(expert, _records(), service=llm), (None, 0.0)
        )

    def test_no_records_skips_the_llm_call(self):
        # Arrange
        llm = MagicMock()
        # Act
        result = adjudication.pick_candidate(make_expert(), [], service=llm)
        # Assert
        self.assertEqual(result, (None, 0.0))
        llm.invoke.assert_not_called()

    def test_prompt_carries_target_and_candidates(self):
        # Arrange
        llm = MagicMock()
        llm.invoke.return_value = '{"candidate_index": null, "confidence": 0}'
        expert = make_expert(affiliation="Stanford University", expertise="genomics")
        # Act
        adjudication.pick_candidate(expert, _records(), service=llm)
        # Assert
        user_prompt = llm.invoke.call_args.args[1]
        self.assertIn("Jane Doe", user_prompt)
        self.assertIn(
            "Affiliation (from our records): Stanford University", user_prompt
        )
        self.assertIn("Candidate 0", user_prompt)
        self.assertIn("Candidate 1", user_prompt)
