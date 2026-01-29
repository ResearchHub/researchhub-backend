from rest_framework import status
from rest_framework.test import APITestCase

from user.tests.helpers import create_random_authenticated_user


class TestFundingDashboardViewSet(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("funder")
        self.overview_url = "/api/funding_dashboard/overview/"
        self.grant_overview_url = "/api/funding_dashboard/grant_overview/"

    def test_overview_requires_authentication(self):
        # Arrange
        self.client.logout()

        # Act
        response = self.client.get(self.overview_url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_overview_returns_200(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(self.overview_url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, dict)

    def test_grant_overview_requires_authentication(self):
        # Arrange
        self.client.logout()

        # Act
        response = self.client.get(self.grant_overview_url, {"grant_id": 1})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_grant_overview_requires_grant_id(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(self.grant_overview_url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_grant_overview_returns_200(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(self.grant_overview_url, {"grant_id": 1})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, dict)
