"""Unit tests for the award-size aim-count policy (pure functions, no Django)."""

import unittest

from research_ai.services.proposal_draft.scope import (
    aim_scope_guidance,
    max_aims_for_budget,
)


class MaxAimsForBudgetTests(unittest.TestCase):
    def test_small_award_funds_one_aim(self):
        # Arrange / Act / Assert: below the $50k tier -> a single aim.
        self.assertEqual(max_aims_for_budget("5000", "USD"), 1)
        self.assertEqual(max_aims_for_budget("49999.99", "USD"), 1)

    def test_mid_award_funds_two_aims(self):
        # Arrange / Act / Assert: the $50k-$100k tier -> two aims.
        self.assertEqual(max_aims_for_budget("50000", "USD"), 2)
        self.assertEqual(max_aims_for_budget("99999", "USD"), 2)

    def test_large_award_funds_three_aims(self):
        # Arrange / Act / Assert: at/above $100k -> three aims.
        self.assertEqual(max_aims_for_budget("100000", "USD"), 3)
        self.assertEqual(max_aims_for_budget("500000", "USD"), 3)

    def test_unknown_or_non_usd_award_imposes_no_cap(self):
        # Arrange / Act / Assert: the dollar tiers do not apply -> None.
        self.assertIsNone(max_aims_for_budget(None, "USD"))
        self.assertIsNone(max_aims_for_budget("not-a-number", "USD"))
        self.assertIsNone(max_aims_for_budget("0", "USD"))
        self.assertIsNone(max_aims_for_budget("100000", "RSC"))


class AimScopeGuidanceTests(unittest.TestCase):
    def test_guidance_names_the_award_and_aim_count(self):
        # Arrange / Act
        guidance = aim_scope_guidance("5000", "USD")

        # Assert: the concrete award and the one-aim cap are stated.
        self.assertIn("$5,000", guidance)
        self.assertIn("one specific aim", guidance)

    def test_guidance_falls_back_to_the_general_rule_when_unknown(self):
        # Arrange / Act: no parseable USD amount -> the general rule, no cap claim.
        guidance = aim_scope_guidance(None, "RSC")

        # Assert
        self.assertIn("Size the number of specific aims", guidance)
        self.assertIn("under $50k", guidance)
