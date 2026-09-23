"""Unit tests for Expert Finder budget and progress helpers."""

from django.test import SimpleTestCase

from research_ai.constants import (
    EXPERT_FINDER_PROGRESS_DISCOVERY_START,
    expert_finder_discovery_progress_percent,
    expert_finder_max_iterations,
    expert_finder_web_search_budget,
)


class ExpertFinderBudgetHelpersTests(SimpleTestCase):
    def test_web_search_budget_floors_and_scales(self):
        # Arrange / Act / Assert
        self.assertEqual(expert_finder_web_search_budget(1), 26)
        self.assertEqual(expert_finder_web_search_budget(10), 35)
        self.assertEqual(expert_finder_web_search_budget(100), 125)
        self.assertEqual(expert_finder_web_search_budget(200), 150)

    def test_max_iterations_floors_and_scales(self):
        # Arrange / Act / Assert
        self.assertEqual(expert_finder_max_iterations(1), 28)
        self.assertEqual(expert_finder_max_iterations(10), 30)
        self.assertEqual(expert_finder_max_iterations(50), 70)
        self.assertEqual(expert_finder_max_iterations(100), 100)

    def test_discovery_progress_maps_to_band(self):
        # Arrange / Act / Assert
        self.assertEqual(expert_finder_discovery_progress_percent(0, 10), 28)
        self.assertEqual(expert_finder_discovery_progress_percent(1, 10), 32)
        self.assertEqual(expert_finder_discovery_progress_percent(10, 10), 70)
        self.assertEqual(expert_finder_discovery_progress_percent(20, 10), 70)
        self.assertEqual(
            expert_finder_discovery_progress_percent(0, 0),
            EXPERT_FINDER_PROGRESS_DISCOVERY_START,
        )
