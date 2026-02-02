from django.test import TestCase

from purchase.services.grant_overview_service import GrantOverviewService
from user.tests.helpers import create_random_authenticated_user


class TestGrantOverviewService(TestCase):
    def setUp(self):
        self.service = GrantOverviewService()
        self.user = create_random_authenticated_user("grant_overview_test")

    def test_get_grant_overview_returns_expected_structure(self):
        # Act
        result = self.service.get_grant_overview(self.user, 1)

        # Assert - verify top-level keys
        self.assertIn("total_raised_usd", result)
        self.assertIn("total_applicants", result)
        self.assertIn("matched_funding_usd", result)
        self.assertIn("recent_updates", result)
        self.assertIn("impact", result)

        # Assert - verify impact structure
        impact = result["impact"]
        self.assertIn("milestones", impact)
        self.assertIn("funding_over_time", impact)
        self.assertIn("topic_breakdown", impact)
        self.assertIn("update_frequency", impact)
        self.assertIn("institutions_supported", impact)

    def test_get_grant_overview_returns_zeros_for_skeleton(self):
        # Act
        result = self.service.get_grant_overview(self.user, 1)

        # Assert - skeleton should return zero values
        self.assertEqual(result["total_raised_usd"], 0.0)
        self.assertEqual(result["matched_funding_usd"], 0.0)
        self.assertEqual(result["total_applicants"], 0)
        self.assertEqual(result["recent_updates"], 0)
