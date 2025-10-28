"""
Unit tests for hybrid search functionality.
"""

import unittest

from search.backends.multi_match_query import MultiMatchQueryBackend


class TestHybridBoolQueryConstruction(unittest.TestCase):
    """Test the construct_hybrid_bool_query static method."""

    def test_construct_hybrid_bool_query_structure(self):
        """Test basic query construction and structure."""
        search_fields = [("title", 3.0), ("authors.full_name", 2.0)]
        query = MultiMatchQueryBackend.construct_hybrid_bool_query(
            "development testing aroma", search_fields
        )

        # Verify it returns a valid query object
        self.assertIsNotNone(query)
        self.assertTrue(hasattr(query, "to_dict"))

        query_dict = query.to_dict()

        # Should be a bool query with should clauses
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

        self.assertIn("title", all_fields)
        self.assertIn("authors.full_name", all_fields)

    def test_query_strategies_and_boosts(self):
        """Test that all three strategies are present with correct boosts."""
        search_fields = [("title", 3.0)]
        query = MultiMatchQueryBackend.construct_hybrid_bool_query(
            "test query", search_fields
        )

        query_dict = query.to_dict()
        should_clauses = query_dict["bool"]["should"]

        # Find and verify phrase match (highest boost)
        phrase_clauses = [c for c in should_clauses if "match_phrase" in c]
        self.assertEqual(len(phrase_clauses), 1)
        self.assertEqual(phrase_clauses[0]["match_phrase"]["title"]["boost"], 3.0)

        # Find and verify match-all (reduced boost)
        match_all_clauses = [
            c
            for c in should_clauses
            if "match" in c and "operator" in c["match"].get("title", {})
        ]
        self.assertEqual(len(match_all_clauses), 1)
        self.assertAlmostEqual(
            match_all_clauses[0]["match"]["title"]["boost"], 2.1, places=5
        )

        # Find and verify fuzzy match (lowest boost)
        fuzzy_clauses = [
            c
            for c in should_clauses
            if "match" in c and "fuzziness" in c["match"].get("title", {})
        ]
        self.assertEqual(len(fuzzy_clauses), 1)
        self.assertAlmostEqual(
            fuzzy_clauses[0]["match"]["title"]["boost"], 0.9, places=5
        )
        self.assertEqual(fuzzy_clauses[0]["match"]["title"]["fuzziness"], "AUTO")

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

        # Verify custom multipliers applied
        self.assertIn(4.0, boosts)  # 2.0 * 2.0 (phrase)
        self.assertIn(1.0, boosts)  # 2.0 * 0.5 (match-all)
        self.assertIn(0.2, boosts)  # 2.0 * 0.1 (fuzzy)


class TestHybridSearchTriggerConditions(unittest.TestCase):
    """Test when hybrid search should trigger without full integration."""

    def test_all_trigger_conditions(self):
        """Test word count, result threshold, and index support."""
        MULTI_MATCH_FIELDS = {"paper": [], "post": []}

        test_cases = [
            # (query, result_count, index, should_trigger, reason)
            ("development and testing", 0, "paper", True, "perfect case"),
            ("development and testing", 2, "post", True, "few results"),
            ("development and testing", 3, "paper", False, "enough results"),
            ("two words", 0, "paper", False, "too few words"),
            ("one two three", 0, "user", False, "unsupported index"),
            ("a b c d", 5, "paper", False, "enough results"),
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


if __name__ == "__main__":
    unittest.main()
