from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from purchase.endaoment.service import CallbackResult, ConnectionStatus
from purchase.endaoment.views import (
    EndaomentCallbackView,
    EndaomentConnectView,
    EndaomentStatusView,
)

User = get_user_model()


class TestEndaomentConnectView(TestCase):
    """
    Tests for the `EndaomentConnectView`.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.service_mock = Mock()
        self.user = User.objects.create_user(username="user1", password="password1")

    def test_post_returns_auth_url(self):
        """
        Test successful OAuth initiation returns authorization URL.
        """
        # Arrange
        self.service_mock.get_authorization_url.return_value = (
            "https://auth.dev.endaoment.org/auth?state=abc1"
        )

        request = self.factory.post(
            "/api/endaoment/connect/",
            {"return_url": "https://researchhub.com/dashboard"},
        )
        force_authenticate(request, user=self.user)

        # Act
        response = EndaomentConnectView.as_view()(request, service=self.service_mock)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["auth_url"], "https://auth.dev.endaoment.org/auth?state=abc1"
        )
        self.service_mock.get_authorization_url.assert_called_once_with(
            self.user.id, "https://researchhub.com/dashboard"
        )

    def test_post_handles_service_exception(self):
        """
        Test that an exception from the service returns a 500 error.
        """
        # Arrange
        self.service_mock.get_authorization_url.side_effect = Exception("D'oh!")

        request = self.factory.post("/api/endaoment/connect/")
        force_authenticate(request, user=self.user)

        # Act
        response = EndaomentConnectView.as_view()(request, service=self.service_mock)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(
            response.data["detail"], "Failed to initiate Endaoment connection"
        )


class TestEndaomentCallbackView(TestCase):
    """
    Tests for the `EndaomentCallbackView`.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.mock_service = Mock()

    def test_successful_callback_redirects(self):
        """
        Test successful OAuth callback redirects to return URL.
        """
        # Arrange
        self.mock_service.process_callback.return_value = CallbackResult(
            success=True, return_url="https://researchhub.com/funding"
        )
        self.mock_service.build_redirect_url.return_value = (
            "https://researchhub.com/funding?endaoment_connected=true"
        )

        request = self.factory.get(
            "/api/endaoment/callback/",
            {"code": "auth_code", "state": "signed_state"},
        )

        # Act
        response = EndaomentCallbackView.as_view()(request, service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, "https://researchhub.com/funding?endaoment_connected=true"
        )
        self.mock_service.process_callback.assert_called_once_with(
            code="auth_code",
            state="signed_state",
            error=None,
        )
        self.mock_service.build_redirect_url.assert_called_once_with(
            error=None, return_url="https://researchhub.com/funding"
        )

    def test_error_callback_redirects_with_error(self):
        """
        Test OAuth callback with error redirects with error param.
        """
        # Arrange
        self.mock_service.process_callback.return_value = CallbackResult(
            success=False, error="cancelled"
        )
        self.mock_service.build_redirect_url.return_value = (
            "https://researchhub.com?endaoment_error=cancelled"
        )

        request = self.factory.get(
            "/api/endaoment/callback/",
            {"error": "access_denied", "state": "signed_state"},
        )

        # Act
        response = EndaomentCallbackView.as_view()(request, service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, "https://researchhub.com?endaoment_error=cancelled"
        )
        self.mock_service.process_callback.assert_called_once_with(
            code=None,
            state="signed_state",
            error="access_denied",
        )
        self.mock_service.build_redirect_url.assert_called_once_with(
            error="cancelled", return_url=None
        )


class TestEndaomentStatusView(TestCase):
    """
    Tests for the `EndaomentStatusView`.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.mock_service = Mock()
        self.user = User.objects.create_user(username="user1", password="password1")

    def test_connected_user(self):
        """
        Test status returns connected with endaoment_user_id.
        """
        # Arrange
        self.mock_service.get_connection_status.return_value = ConnectionStatus(
            connected=True, endaoment_user_id="externalUserId1"
        )

        request = self.factory.get("/api/endaoment/status/")
        force_authenticate(request, user=self.user)

        # Act
        response = EndaomentStatusView.as_view()(request, service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["connected"])
        self.assertEqual(response.data["endaoment_user_id"], "externalUserId1")
        self.mock_service.get_connection_status.assert_called_once_with(self.user)

    def test_unconnected_user(self):
        """
        Test status returns not connected.
        """
        # Arrange
        self.mock_service.get_connection_status.return_value = ConnectionStatus(
            connected=False
        )

        request = self.factory.get("/api/endaoment/status/")
        force_authenticate(request, user=self.user)

        # Act
        response = EndaomentStatusView.as_view()(request, service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["connected"])
        self.assertIsNone(response.data["endaoment_user_id"])
