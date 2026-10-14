"""Unit tests for Expert Finder budget helpers."""

from django.test import SimpleTestCase

from research_ai.constants import (
    EXPERT_FINDER_BATCH_CHASE_RATIO,
    expert_finder_max_iterations,
    expert_finder_web_search_budget,
)


class ExpertFinderBudgetHelpersTests(SimpleTestCase):
    def test_batch_chase_ratio(self):
        # Arrange / Act / Assert
        self.assertEqual(EXPERT_FINDER_BATCH_CHASE_RATIO, 0.30)

    def test_web_search_budget_scales_with_target(self):
        # Arrange / Act / Assert — ~6 searches per expert target, floor 80.
        self.assertEqual(expert_finder_web_search_budget(1), 80)
        self.assertEqual(expert_finder_web_search_budget(10), 80)
        self.assertEqual(expert_finder_web_search_budget(25), 150)
        self.assertEqual(expert_finder_web_search_budget(50), 200)
        self.assertEqual(expert_finder_web_search_budget(100), 200)

    def test_max_iterations_floors_and_scales(self):
        # Arrange / Act / Assert
        self.assertEqual(expert_finder_max_iterations(1), 60)
        self.assertEqual(expert_finder_max_iterations(10), 60)
        self.assertEqual(expert_finder_max_iterations(50), 140)
        self.assertEqual(expert_finder_max_iterations(100), 150)
