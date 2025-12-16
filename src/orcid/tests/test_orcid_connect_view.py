from unittest.mock import patch

from allauth.socialaccount.models import SocialApp
from rest_framework import status
from rest_framework.test import APITestCase

from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_authenticated_user


@patch("orcid.views.orcid_connect_view.OrcidService")
class OrcidConnectViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("orcid_user")
        self.client.force_authenticate(user=self.user)
        create_orcid_app()

    def test_returns_auth_url(self, mock_service):
        # Arrange
        mock_service.return_value.build_auth_url.return_value = "https://orcid.org/oauth?state=abc"

        # Act
        response = self.client.post("/api/orcid/connect/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["auth_url"], "https://orcid.org/oauth?state=abc")
        mock_service.return_value.build_auth_url.assert_called_once_with(self.user.id, None)

    def test_returns_auth_url_with_return_url(self, mock_service):
        # Arrange
        mock_service.return_value.build_auth_url.return_value = "https://orcid.org/oauth?state=abc"

        # Act
        response = self.client.post("/api/orcid/connect/", {"return_url": "https://researchhub.com/funds"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_service.return_value.build_auth_url.assert_called_once_with(self.user.id, "https://researchhub.com/funds")

    def test_unauthenticated_rejected(self, mock_service):
        # Arrange
        self.client.force_authenticate(user=None)

        # Act
        response = self.client.post("/api/orcid/connect/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_orcid_app_returns_500(self, mock_service):
        # Arrange
        mock_service.return_value.build_auth_url.side_effect = SocialApp.DoesNotExist()

        # Act
        response = self.client.post("/api/orcid/connect/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["error"], "ORCID not configured")

    def test_unexpected_error_returns_500(self, mock_service):
        # Arrange
        mock_service.return_value.build_auth_url.side_effect = RuntimeError("error")

        # Act
        response = self.client.post("/api/orcid/connect/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["error"], "Failed to initiate ORCID connection")

