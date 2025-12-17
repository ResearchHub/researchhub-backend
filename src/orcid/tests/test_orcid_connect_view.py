from unittest.mock import Mock

from allauth.socialaccount.models import SocialApp
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from orcid.views.orcid_connect_view import OrcidConnectView
from user.tests.helpers import create_random_default_user


class OrcidConnectViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = OrcidConnectView.as_view()
        self.user = create_random_default_user("orcid_user")
        self.mock_service = Mock()

    def test_returns_auth_url(self):
        # Arrange
        self.mock_service.build_auth_url.return_value = "https://orcid.org/oauth?state=abc"
        request = self.factory.post("/api/orcid/connect/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["auth_url"], "https://orcid.org/oauth?state=abc")
        self.mock_service.build_auth_url.assert_called_once_with(self.user.id, None)

    def test_returns_auth_url_with_return_url(self):
        # Arrange
        self.mock_service.build_auth_url.return_value = "https://orcid.org/oauth?state=abc"
        request = self.factory.post(
            "/api/orcid/connect/",
            {"return_url": "https://researchhub.com/funds"},
            format="json",
        )
        force_authenticate(request, user=self.user)

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.mock_service.build_auth_url.assert_called_once_with(self.user.id, "https://researchhub.com/funds")

    def test_unauthenticated_rejected(self):
        # Arrange
        request = self.factory.post("/api/orcid/connect/")

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_orcid_app_returns_500(self):
        # Arrange
        self.mock_service.build_auth_url.side_effect = SocialApp.DoesNotExist()
        request = self.factory.post("/api/orcid/connect/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["error"], "ORCID not configured")

    def test_unexpected_error_returns_500(self):
        # Arrange
        self.mock_service.build_auth_url.side_effect = RuntimeError("error")
        request = self.factory.post("/api/orcid/connect/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["error"], "Failed to initiate ORCID connection")

