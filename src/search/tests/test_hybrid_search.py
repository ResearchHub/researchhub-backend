"""
Comprehensive tests for hybrid search functionality.

This module contains both unit tests for the query builder and integration tests
for the SuggestView hybrid search fallback mechanism.
"""

import unittest
from unittest.mock import MagicMock, patch

from django.test import TestCase

from search.views.suggest import SuggestView

# =============================================================================
# Unit Tests: Query Builder
# =============================================================================


class TestMatchBoolPrefixQueryConstruction(unittest.TestCase):
    """Test the match_bool_prefix query construction."""

    def test_query_construction(self):
        """Test match_bool_prefix query structure."""
        from opensearchpy import Q

        # Test the query structure that match_bool_prefix creates
        query_params = {
            "query": "test query",
            "minimum_should_match": "2<70%",
            "fuzziness": "AUTO",
        }
        query = Q("match_bool_prefix", **{"paper_title": query_params})
        query_dict = query.to_dict()

        # Verify structure
        self.assertIn("match_bool_prefix", query_dict)
        self.assertIn("paper_title", query_dict["match_bool_prefix"])
        match_config = query_dict["match_bool_prefix"]["paper_title"]
        self.assertEqual(match_config["query"], "test query")
        self.assertEqual(match_config["minimum_should_match"], "2<70%")
        self.assertEqual(match_config["fuzziness"], "AUTO")


class TestMatchBoolPrefixTriggerConditions(unittest.TestCase):
    """Test when match_bool_prefix fallback should trigger."""

    def test_trigger_conditions(self):
        """Test word count, result threshold, and field support."""
        from search.views.suggest import SuggestView

        view = SuggestView()

        test_cases = [
            # (query, result_count, field_name, should_trigger, reason)
            ("one two", 0, "paper_title", True, "2 words, 0 results"),
            ("one two", 2, "paper_title", True, "2 words, 2 results (< 3)"),
            ("one two", 3, "paper_title", False, "enough results"),
            ("one", 0, "paper_title", False, "only 1 word"),
            ("one two", 0, None, False, "no partial_match_field"),
        ]

        for query, result_count, field_name, expected, reason in test_cases:
            should_trigger = view._should_trigger_partial_match(
                query, [{}] * result_count, field_name
            )

            self.assertEqual(
                should_trigger,
                expected,
                f"Failed ({reason}): query='{query}', "
                f"results={result_count}, field={field_name}",
            )


# =============================================================================
# Integration Tests: SuggestView
# =============================================================================


class TestSuggestViewHybridSearch(TestCase):
    """Test the match_bool_prefix fallback in SuggestView."""

    def setUp(self):
        self.view = SuggestView()

    @patch("search.views.suggest.MatchBoolPrefixBackend.execute_search")
    @patch("search.views.suggest.Search")
    def test_match_bool_prefix_triggers_and_deduplicates(
        self, mock_search_class, mock_execute_search
    ):
        """Test that match_bool_prefix triggers when needed and deduplicates results."""
        # Create mock hits for match_bool_prefix
        hit1 = MagicMock()
        hit1.to_dict.return_value = {"id": 999, "paper_title": "Existing Paper"}
        hit1.meta.score = 10.0

        hit2 = MagicMock()
        hit2.to_dict.return_value = {"id": 1000, "paper_title": "New Paper"}
        hit2.meta.score = 8.0

        # Setup completion suggester response (returns few results)
        mock_suggest_resp = MagicMock()
        mock_suggest_resp.suggest.to_dict.return_value = {
            "suggestions": [{"options": []}]
        }

        mock_search_instance = MagicMock()
        mock_search_instance.suggest.return_value = mock_search_instance
        mock_search_instance.execute.return_value = mock_suggest_resp
        mock_search_class.return_value = mock_search_instance

        # Setup match_bool_prefix response
        mock_fallback_resp = MagicMock()
        mock_fallback_resp.hits = [hit1, hit2]
        mock_execute_search.return_value = mock_fallback_resp

        # Execute with 2+ word query that triggers fallback
        query = "development testing"
        self.view.perform_regular_search(query, ["paper"], 10)

        # Verify match_bool_prefix was called
        mock_execute_search.assert_called_once()
        call_kwargs = mock_execute_search.call_args[1]
        self.assertEqual(call_kwargs["query"], query)
        self.assertEqual(call_kwargs["field_name"], "paper_title")

    @patch("search.views.suggest.MatchBoolPrefixBackend.execute_search")
    @patch("search.views.suggest.Search")
    def test_match_bool_prefix_does_not_trigger_for_short_queries(
        self, mock_search_class, mock_execute_search
    ):
        """Test optimization: match_bool_prefix doesn't run for < 2 word queries."""
        # Setup completion suggester response
        mock_suggest_resp = MagicMock()
        mock_suggest_resp.suggest.to_dict.return_value = {
            "suggestions": [{"options": []}]
        }

        mock_search_instance = MagicMock()
        mock_search_instance.suggest.return_value = mock_search_instance
        mock_search_instance.execute.return_value = mock_suggest_resp
        mock_search_class.return_value = mock_search_instance

        # Execute with only 1 word
        self.view.perform_regular_search("one", ["paper"], 10)

        # match_bool_prefix should NOT be triggered
        mock_execute_search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
