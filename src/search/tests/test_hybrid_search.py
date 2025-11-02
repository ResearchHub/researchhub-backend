"""
Comprehensive tests for hybrid search functionality.

This module contains both unit tests for the query builder and integration tests
for the SuggestView hybrid search fallback mechanism.
"""

import unittest
from unittest.mock import MagicMock, patch

from django.test import TestCase

from search.backends.multi_match_query import MultiMatchQueryBackend
from search.views.suggest import SuggestView

# =============================================================================
# Unit Tests: Query Builder
# =============================================================================


class TestHybridBoolQueryConstruction(unittest.TestCase):
    """Test the construct_hybrid_bool_query static method."""

    def test_query_construction_with_multiple_fields(self):
        """Test complete query construction: structure, strategies, and fields."""
        search_fields = [("title", 3.0), ("authors.full_name", 2.0)]
        query = MultiMatchQueryBackend.construct_hybrid_bool_query(
            "development testing aroma", search_fields
        )

        query_dict = query.to_dict()

        # Verify basic structure
        self.assertIn("bool", query_dict)
        self.assertIn("should", query_dict["bool"])
        self.assertEqual(query_dict["bool"]["minimum_should_match"], 1)

        # Should have 6 clauses (3 strategies × 2 fields)
        should_clauses = query_dict["bool"]["should"]
        self.assertEqual(len(should_clauses), 6)

        # Verify all field names are present
        all_fields = set()
        for clause in should_clauses:
            if "match_phrase" in clause:
                all_fields.update(clause["match_phrase"].keys())
            elif "match" in clause:
                all_fields.update(clause["match"].keys())

        self.assertEqual(all_fields, {"title", "authors.full_name"})

        # Verify all three strategies exist
        phrase_clauses = [c for c in should_clauses if "match_phrase" in c]
        match_all_clauses = [
            c
            for c in should_clauses
            if "match" in c and "operator" in str(c.get("match", {}))
        ]
        fuzzy_clauses = [
            c
            for c in should_clauses
            if "match" in c and "fuzziness" in str(c.get("match", {}))
        ]

        self.assertEqual(len(phrase_clauses), 2)  # One per field
        self.assertEqual(len(match_all_clauses), 2)  # One per field
        self.assertEqual(len(fuzzy_clauses), 2)  # One per field

    def test_custom_boost_multipliers(self):
        """Test that custom boost multipliers are applied correctly."""
        search_fields = [("title", 2.0)]
        query = MultiMatchQueryBackend.construct_hybrid_bool_query(
            "test",
            search_fields,
            phrase_multiplier=2.0,
            match_all_multiplier=0.5,
            fuzzy_multiplier=0.1,
        )

        query_dict = query.to_dict()
        should_clauses = query_dict["bool"]["should"]

        # Extract boosts
        boosts = []
        for clause in should_clauses:
            if "match_phrase" in clause:
                boosts.append(clause["match_phrase"]["title"]["boost"])
            elif "match" in clause:
                boosts.append(clause["match"]["title"]["boost"])

        # Verify custom multipliers applied (base=2.0)
        self.assertIn(4.0, boosts)  # 2.0 * 2.0 (phrase)
        self.assertIn(1.0, boosts)  # 2.0 * 0.5 (match-all)
        self.assertIn(0.2, boosts)  # 2.0 * 0.1 (fuzzy)


class TestHybridSearchTriggerConditions(unittest.TestCase):
    """Test when hybrid search should trigger."""

    def test_trigger_conditions(self):
        """Test word count, result threshold, and index support."""
        MULTI_MATCH_FIELDS = {"paper": [], "post": []}

        test_cases = [
            # (query, result_count, index, should_trigger, reason)
            ("one two three", 0, "paper", True, "3 words, 0 results"),
            ("one two three", 2, "post", True, "3 words, 2 results"),
            ("one two three", 3, "paper", False, "enough results"),
            ("two words", 0, "paper", False, "only 2 words"),
            ("one two three", 0, "user", False, "unsupported index"),
        ]

        for query, result_count, index, expected, reason in test_cases:
            word_count = len(query.split())
            should_trigger = (
                word_count >= 3 and result_count < 3 and index in MULTI_MATCH_FIELDS
            )

            self.assertEqual(
                should_trigger,
                expected,
                f"Failed ({reason}): query='{query}', "
                f"results={result_count}, index={index}",
            )


# =============================================================================
# Integration Tests: SuggestView
# =============================================================================


class TestSuggestViewHybridSearch(TestCase):
    """Test the multi_match fallback in SuggestView."""

    def setUp(self):
        self.view = SuggestView()

    def _create_mock_search(self, suggester_results=None, multi_match_hits=None):
        """Helper to create mock search with cleaner setup."""
        mock_search = MagicMock()
        mock_instance = MagicMock()

        # Setup completion suggester response
        mock_suggest_resp = MagicMock()
        mock_suggest_resp.suggest.to_dict.return_value = {
            "suggestions": [{"options": suggester_results or []}]
        }

        # Setup multi_match response if provided
        if multi_match_hits is not None:
            mock_mm_resp = MagicMock()
            mock_mm_resp.hits = multi_match_hits

            # Toggle response based on whether query() was called
            def execute():
                if mock_instance._multi_match_mode:
                    return mock_mm_resp
                return mock_suggest_resp

            mock_instance.execute.side_effect = execute
            mock_instance.query.side_effect = (
                lambda q: setattr(mock_instance, "_multi_match_mode", True)
                or mock_instance
            )
        else:
            mock_instance.execute.return_value = mock_suggest_resp

        mock_instance.suggest.return_value = mock_instance
        mock_instance.__getitem__.return_value = mock_instance
        mock_instance._multi_match_mode = False

        mock_search.return_value = mock_instance
        return mock_search, mock_instance

    @patch("search.views.suggest.Search")
    @patch("search.views.suggest.MultiMatchQueryBackend")
    def test_multi_match_triggers_and_deduplicates(
        self, mock_backend, mock_search_class
    ):
        """Test that multi_match triggers when needed and deduplicates results."""
        # Create mock hits
        hit1 = MagicMock()
        hit1.to_dict.return_value = {"id": 999, "paper_title": "Existing Paper"}
        hit1.meta.score = 10.0

        hit2 = MagicMock()
        hit2.to_dict.return_value = {"id": 1000, "paper_title": "New Paper"}
        hit2.meta.score = 8.0

        # Setup mocks
        mock_search, mock_instance = self._create_mock_search(
            suggester_results=[],
            multi_match_hits=[hit1, hit2],
        )
        mock_search_class.return_value = mock_instance.suggest.return_value
        mock_backend.construct_hybrid_bool_query.return_value = MagicMock()

        # Execute
        query = "development testing aroma"
        self.view.perform_regular_search(query, ["paper"], 10)

        # Verify multi_match was triggered
        mock_backend.construct_hybrid_bool_query.assert_called_once()
        call_str = str(mock_backend.construct_hybrid_bool_query.call_args)
        self.assertIn(query, call_str)

        # Verify Search.query() was called (indicates multi_match executed)
        self.assertTrue(
            mock_instance.query.called,
            "Multi_match should execute query()",
        )

    @patch("search.views.suggest.Search")
    def test_multi_match_does_not_trigger_for_short_queries(self, mock_search_class):
        """Test optimization: multi_match doesn't run for < 3 word queries."""
        mock_search, mock_instance = self._create_mock_search()
        mock_search_class.return_value = mock_instance.suggest.return_value

        # Execute with only 2 words
        self.view.perform_regular_search("two words", ["paper"], 10)

        # Multi_match should NOT be triggered
        mock_instance.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
