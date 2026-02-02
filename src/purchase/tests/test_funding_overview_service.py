from django.test import TestCase

from purchase.services.funding_overview_service import FundingOverviewService
from user.tests.helpers import create_random_authenticated_user


class TestFundingOverviewService(TestCase):
    def setUp(self):
        self.service = FundingOverviewService()
        self.user = create_random_authenticated_user("funding_overview_test")

    def test_get_funding_overview_returns_expected_structure(self):
        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert - verify top-level keys
        self.assertIn("total_distributed_usd", result)
        self.assertIn("active_grants", result)
        self.assertIn("total_applicants", result)
        self.assertIn("matched_funding_usd", result)
        self.assertIn("recent_updates", result)
        self.assertIn("proposals_funded", result)
        self.assertIn("impact", result)

        # Assert - verify impact structure
        impact = result["impact"]
        self.assertIn("milestones", impact)
        self.assertIn("funding_over_time", impact)
        self.assertIn("topic_breakdown", impact)
        self.assertIn("update_frequency", impact)
        self.assertIn("institutions_supported", impact)

    def test_get_funding_overview_returns_zeros_for_new_user(self):
        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert - new user should have zero values
        self.assertEqual(result["total_distributed_usd"], 0.0)
        self.assertEqual(result["matched_funding_usd"], 0.0)
        self.assertEqual(result["total_applicants"], 0)
        self.assertEqual(result["proposals_funded"], 0)
        self.assertEqual(result["recent_updates"], 0)

