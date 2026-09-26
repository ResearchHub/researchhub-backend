from unittest.mock import Mock

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from research_ai.models import OutreachMailboxConnection
from research_ai.services.outreach.gmail_oauth import GmailOAuthConfigError
from research_ai.views.mailbox_views import (
    OutreachMailboxCallbackView,
    OutreachMailboxConnectView,
    OutreachMailboxView,
)
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
)


@override_settings(
    GMAIL_OUTREACH_FRONTEND_RETURN_URL=("http://localhost:3000/expert-finder/settings"),
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

    def test_connect_returns_auth_url_and_state(self):
        # Arrange
        self.mock_service.build_auth_url.return_value = {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?x=1",
            "state": "signed-state",
        }
        request = self.factory.get(
            "/api/research_ai/expert-finder/mailbox/connect/",
            {"return_url": "http://localhost:3000/settings"},
        )
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], "signed-state")
        self.mock_service.build_auth_url.assert_called_once_with(
            self.editor.id, "http://localhost:3000/settings"
        )

    def test_connect_missing_config_returns_500(self):
        # Arrange
        self.mock_service.build_auth_url.side_effect = GmailOAuthConfigError()
        request = self.factory.get("/api/research_ai/expert-finder/mailbox/connect/")
        force_authenticate(request, user=self.editor)

        # Act
        response = OutreachMailboxConnectView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("not configured", response.data["detail"])

    def test_callback_redirects_on_success(self):
        # Arrange
        self.mock_service.process_callback.return_value = (
            "http://localhost:3000/expert-finder/settings?gmail=connected"
        )
        request = self.factory.get(
            "/api/research_ai/expert-finder/mailbox/callback/",
            {"code": "abc", "state": "st"},
        )

        # Act
        response = OutreachMailboxCallbackView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("gmail=connected", response.url)
        self.mock_service.process_callback.assert_called_once_with(
            code="abc", state="st"
        )

    def test_callback_cancelled_redirects_with_error(self):
        # Arrange
        self.mock_service.get_redirect_url.return_value = (
            "http://localhost:3000/expert-finder/settings?gmail=error"
        )
        request = self.factory.get(
            "/api/research_ai/expert-finder/mailbox/callback/",
            {"error": "access_denied"},
        )

        # Act
        response = OutreachMailboxCallbackView.as_view()(
            request, gmail_oauth_service=self.mock_service
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("gmail=error", response.url)
        self.mock_service.get_redirect_url.assert_called_once_with(error="error")
