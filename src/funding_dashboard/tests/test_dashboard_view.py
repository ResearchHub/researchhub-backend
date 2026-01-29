import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from user.models import User


class FundingDashboardViewTest(TestCase):

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser", email="test@test.com", password=uuid.uuid4().hex
        )
        self.url = "/api/funding_dashboard/overview/"
        RscExchangeRate.objects.create(rate=1.0, real_rate=1.0)

    def test_requires_authentication(self) -> None:
        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_portfolio_overview_structure(self) -> None:
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("total_distributed_usd", data)
        self.assertIn("active_rfps", data)
        self.assertIn("total_applicants", data)
        self.assertIn("matched_funding_usd", data)
        self.assertIn("recent_updates", data)
        self.assertIn("proposals_funded", data)

    def test_returns_impact_data_structure(self) -> None:
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(self.url)

        # Assert
        data = response.json()
        impact = data["impact"]
        self.assertIn("milestones", impact)
        self.assertIn("funding_over_time", impact)
        self.assertIn("topic_breakdown", impact)
        self.assertIn("update_frequency", impact)
        self.assertIn("institutions_supported", impact)

        self.assertEqual(len(impact["funding_over_time"]), 6)
        self.assertEqual(len(impact["update_frequency"]), 4)

    def test_returns_milestone_structure(self) -> None:
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(self.url)

        # Assert
        milestones = response.json()["impact"]["milestones"]
        for key in ["funding_contributed", "researchers_supported", "matched_funding"]:
            self.assertIn("current", milestones[key])
            self.assertIn("target", milestones[key])

    def test_rejects_non_get_methods(self) -> None:
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act & Assert
        self.assertEqual(
            self.client.post(self.url, {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )
        self.assertEqual(
            self.client.put(self.url, {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )
        self.assertEqual(
            self.client.delete(self.url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )
