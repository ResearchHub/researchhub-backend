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
        # Arrange - unauthenticated client from setUp

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
        self.assertIsInstance(data["total_distributed_usd"], (int, float))
        self.assertIsInstance(data["active_rfps"]["active"], int)
        self.assertIsInstance(data["active_rfps"]["total"], int)
        self.assertIsInstance(data["total_applicants"], int)
        self.assertIsInstance(data["matched_funding_usd"], (int, float))
        self.assertIsInstance(data["recent_updates"], int)
        self.assertIsInstance(data["proposals_funded"], int)

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
