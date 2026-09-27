from unittest.mock import Mock

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from research_ai.models import OutreachMailboxConnection
from research_ai.services.outreach.gmail_oauth import (
    GmailMailboxNotAllowedError,
    GmailOAuthConfigError,
)
from research_ai.views.mailbox_views import (
    OutreachMailboxConnectView,
    OutreachMailboxView,
)
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
)

_FE_REDIRECT = "http://localhost:3000/expert-finder/settings"


@override_settings(
    GMAIL_OUTREACH_REDIRECT_URI=_FE_REDIRECT,
)
class OutreachMailboxViewTests(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.editor, _hub = create_hub_editor("mailbox_editor", "Mailbox Hub")
        self.user = create_random_authenticated_user("mailbox_user", moderator=False)
        self.moderator = create_random_authenticated_user("mailbox_mod", moderator=True)
        self.mock_service = Mock()

    def test_status_requires_auth(self):
        # Arrange
        request = self.factory.get("/api/research_ai/expert-finder/mailbox/")

        # Act
        response = OutreachMailboxView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_status_rejects_non_editor(self):
        # Arrange
        request = self.factory.get("/api/research_ai/expert-finder/mailbox/")
        force_authenticate(request, user=self.user)

        # Act
        response = OutreachMailboxView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_status_returns_connection_payload_for_editor(self):
        # Arrange
        self.mock_service.get_connection_status.return_value = {
            "connected": True,
            "email": "editor@gmail.com",
            "status": OutreachMailboxConnection.Status.ACTIVE,
            "last_error": None,
        }
        request = self.factory.get("/api/research_ai/expert-finder/mailbox/")
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "editor@gmail.com")
        self.mock_service.get_connection_status.assert_called_once_with(self.editor)

    def test_disconnect_calls_service(self):
        # Arrange
        self.mock_service.disconnect.return_value = {
            "connected": False,
            "email": None,
            "status": OutreachMailboxConnection.Status.REVOKED,
            "last_error": None,
        }
        request = self.factory.delete("/api/research_ai/expert-finder/mailbox/")
        force_authenticate(request, user=self.moderator)

        # Act
        response = OutreachMailboxView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.mock_service.disconnect.assert_called_once_with(self.moderator)

    def test_connect_get_returns_client_id_scopes_and_redirect(self):
        # Arrange
        self.mock_service.get_connect_params.return_value = {
            "client_id": "google-client-id",
            "scopes": [
                "openid",
                "email",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
            "redirect_uri": _FE_REDIRECT,
        }
        request = self.factory.get("/api/research_ai/expert-finder/mailbox/connect/")
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["client_id"], "google-client-id")
        self.assertEqual(response.data["redirect_uri"], _FE_REDIRECT)
        self.assertIn(
            "https://www.googleapis.com/auth/gmail.send", response.data["scopes"]
        )
        self.mock_service.get_connect_params.assert_called_once_with()

    def test_connect_get_missing_config_returns_500(self):
        # Arrange
        self.mock_service.get_connect_params.side_effect = GmailOAuthConfigError()
        request = self.factory.get("/api/research_ai/expert-finder/mailbox/connect/")
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("not configured", response.data["detail"])

    def test_connect_post_exchanges_code_for_editor(self):
        # Arrange
        self.mock_service.connect_with_code.return_value = {
            "connected": True,
            "email": "editor@gmail.com",
            "status": OutreachMailboxConnection.Status.ACTIVE,
            "last_error": None,
        }
        request = self.factory.post(
            "/api/research_ai/expert-finder/mailbox/connect/",
            {"code": "auth-code", "redirect_uri": _FE_REDIRECT},
            format="json",
        )
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "editor@gmail.com")
        self.mock_service.connect_with_code.assert_called_once_with(
            self.editor, code="auth-code", redirect_uri=_FE_REDIRECT
        )

    def test_connect_post_requires_code_and_redirect_uri(self):
        # Arrange
        request = self.factory.post(
            "/api/research_ai/expert-finder/mailbox/connect/",
            {"code": "auth-code"},
            format="json",
        )
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_service.connect_with_code.assert_not_called()

    def test_connect_post_rejects_disallowed_mailbox(self):
        # Arrange
        self.mock_service.connect_with_code.side_effect = GmailMailboxNotAllowedError(
            "user@researchhub.foundation"
        )
        request = self.factory.post(
            "/api/research_ai/expert-finder/mailbox/connect/",
            {"code": "auth-code", "redirect_uri": _FE_REDIRECT},
            format="json",
        )
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "mailbox_not_allowed")
        self.assertEqual(response.data["email"], "user@researchhub.foundation")

    def test_connect_post_requires_auth(self):
        # Arrange
        request = self.factory.post(
            "/api/research_ai/expert-finder/mailbox/connect/",
            {"code": "auth-code", "redirect_uri": _FE_REDIRECT},
            format="json",
        )

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
