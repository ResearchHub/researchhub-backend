import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from user.models import User


class FundingDashboardViewTest(TestCase):

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(username="t", email="t@t.com", password=uuid.uuid4().hex)
        self.url = "/api/funding_dashboard/overview/"
        RscExchangeRate.objects.create(rate=1.0, real_rate=1.0)

    def test_requires_authentication(self) -> None:
        # Arrange - no authentication

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_complete_response_structure(self) -> None:
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        for key in ["total_distributed_usd", "active_rfps", "total_applicants", "matched_funding_usd", "recent_updates", "proposals_funded"]:
            self.assertIn(key, data)
        for key in ["milestones", "funding_over_time", "topic_breakdown", "update_frequency", "institutions_supported"]:
            self.assertIn(key, data["impact"])
        for m in ["funding_contributed", "researchers_supported", "matched_funding"]:
            self.assertIn("current", data["impact"]["milestones"][m])
            self.assertIn("target", data["impact"]["milestones"][m])
        self.assertEqual(len(data["impact"]["funding_over_time"]), 6)
        self.assertEqual(len(data["impact"]["update_frequency"]), 4)

    def test_rejects_non_get_methods(self) -> None:
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act & Assert
        self.assertEqual(self.client.post(self.url, {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.put(self.url, {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.delete(self.url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
