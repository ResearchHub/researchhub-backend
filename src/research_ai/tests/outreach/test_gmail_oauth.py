from unittest.mock import Mock

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.core import signing
from django.test import TestCase, override_settings

from research_ai.models import OutreachMailboxConnection
from research_ai.services.outreach.gmail_oauth import (
    GmailMailboxNotAllowedError,
    GmailOAuthService,
    get_google_oauth_credentials,
)
from user.tests.helpers import create_random_default_user


def _create_google_social_app(
    client_id: str = "google-client-id", secret: str = "google-secret"
) -> SocialApp:
    app = SocialApp.objects.create(
        provider="google",
        name="Google",
        client_id=client_id,
        secret=secret,
    )
    app.sites.add(Site.objects.get_current())
    return app


@override_settings(
    GMAIL_OUTREACH_REDIRECT_URI=(
        "http://localhost:8000/api/research_ai/expert-finder/mailbox/callback/"
    ),
    GMAIL_OUTREACH_FRONTEND_RETURN_URL=("http://localhost:3000/expert-finder/settings"),
    CORS_ALLOWED_ORIGINS=["http://localhost:3000", "https://researchhub.com"],
)
class GmailOAuthServiceTests(TestCase):
    def setUp(self):
        self.mock_client = Mock()
        self.service = GmailOAuthService(client=self.mock_client)
        _create_google_social_app()

    def test_get_google_oauth_credentials_from_social_app(self):
        # Act
        client_id, secret = get_google_oauth_credentials()

        # Assert
        self.assertEqual(client_id, "google-client-id")
        self.assertEqual(secret, "google-secret")

    @override_settings(
        GOOGLE_CLIENT_ID="settings-client",
        GOOGLE_CLIENT_SECRET="settings-secret",
    )
    def test_get_google_oauth_credentials_falls_back_to_settings(self):
        # Arrange
        SocialApp.objects.filter(provider="google").delete()

        # Act
        client_id, secret = get_google_oauth_credentials()

        # Assert
        self.assertEqual(client_id, "settings-client")
        self.assertEqual(secret, "settings-secret")

    def test_build_auth_url_includes_gmail_scopes_and_offline_consent(self):
        # Arrange
        user = create_random_default_user("editor")

        # Act
        payload = self.service.build_auth_url(user.id)

        # Assert
        self.assertIn("auth_url", payload)
        self.assertIn("state", payload)
        self.assertIn("gmail.send", payload["auth_url"])
        self.assertIn("gmail.readonly", payload["auth_url"])
        self.assertIn("access_type=offline", payload["auth_url"])
        self.assertIn("prompt=consent", payload["auth_url"])
        state_data = signing.loads(payload["state"])
        self.assertEqual(state_data["user_id"], user.id)

    def test_process_callback_accepts_gmail_com(self):
        # Arrange
        user = create_random_default_user("gmail_ok")
        self.mock_client.exchange_code_for_token.return_value = {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "scope": (
                "openid email https://www.googleapis.com/auth/gmail.send "
                "https://www.googleapis.com/auth/gmail.readonly"
            ),
        }
        self.mock_client.fetch_userinfo.return_value = {
            "email": "Editor@Gmail.com",
        }
        state = signing.dumps({"user_id": user.id})

        # Act
        result = self.service.process_callback("auth-code", state)

        # Assert
        self.assertIn("gmail=connected", result)
        connection = OutreachMailboxConnection.objects.get(user=user)
        self.assertEqual(connection.email, "editor@gmail.com")
        self.assertEqual(connection.status, OutreachMailboxConnection.Status.ACTIVE)
        self.assertEqual(connection.access_token, "access-1")
        self.assertEqual(connection.refresh_token, "refresh-1")
        self.assertNotEqual(connection.access_token, "")  # encrypted at rest OK

    def test_process_callback_accepts_googlemail_com(self):
        # Arrange
        user = create_random_default_user("googlemail_ok")
        self.mock_client.exchange_code_for_token.return_value = {
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
        }
        self.mock_client.fetch_userinfo.return_value = {
            "email": "user@googlemail.com",
        }
        state = signing.dumps({"user_id": user.id})

        # Act
        result = self.service.process_callback("auth-code", state)

        # Assert
        self.assertIn("gmail=connected", result)
        self.assertEqual(
            OutreachMailboxConnection.objects.get(user=user).email,
            "user@googlemail.com",
        )

    def test_process_callback_rejects_researchhub_foundation(self):
        # Arrange
        user = create_random_default_user("rh_foundation")
        self.mock_client.exchange_code_for_token.return_value = {
            "access_token": "access-3",
            "refresh_token": "refresh-3",
            "expires_in": 3600,
        }
        self.mock_client.fetch_userinfo.return_value = {
            "email": "user@researchhub.foundation",
        }
        state = signing.dumps({"user_id": user.id})

        # Act
        result = self.service.process_callback("auth-code", state)

        # Assert
        self.assertIn("gmail=error", result)
        self.assertFalse(OutreachMailboxConnection.objects.filter(user=user).exists())

    def test_process_callback_rejects_researchhub_com(self):
        # Arrange
        user = create_random_default_user("rh_com")
        self.mock_client.exchange_code_for_token.return_value = {
            "access_token": "access-4",
            "refresh_token": "refresh-4",
            "expires_in": 3600,
        }
        self.mock_client.fetch_userinfo.return_value = {
            "email": "editor@researchhub.com",
        }
        state = signing.dumps({"user_id": user.id})

        # Act
        result = self.service.process_callback("auth-code", state)

        # Assert
        self.assertIn("gmail=error", result)
        self.assertFalse(OutreachMailboxConnection.objects.filter(user=user).exists())

    def test_email_from_token_response_raises_for_disallowed_domain(self):
        # Arrange
        self.mock_client.fetch_userinfo.return_value = {
            "email": "user@researchhub.foundation",
        }

        # Act / Assert
        with self.assertRaises(GmailMailboxNotAllowedError):
            self.service._email_from_token_response({"access_token": "tok"})

    def test_disconnect_revokes_and_marks_revoked(self):
        # Arrange
        user = create_random_default_user("disconnect")
        OutreachMailboxConnection.objects.create(
            user=user,
            email="editor@gmail.com",
            access_token="access",
            refresh_token="refresh",
            status=OutreachMailboxConnection.Status.ACTIVE,
        )

        # Act
        payload = self.service.disconnect(user)

        # Assert
        self.mock_client.revoke_token.assert_called_once_with("refresh")
        connection = OutreachMailboxConnection.objects.get(user=user)
        self.assertEqual(connection.status, OutreachMailboxConnection.Status.REVOKED)
        self.assertFalse(payload["connected"])
        self.assertEqual(payload["status"], OutreachMailboxConnection.Status.REVOKED)

    def test_get_connection_status_not_connected(self):
        # Arrange
        user = create_random_default_user("noconn")

        # Act
        payload = self.service.get_connection_status(user)

        # Assert
        self.assertEqual(
            payload,
            {
                "connected": False,
                "email": None,
                "status": None,
                "last_error": None,
            },
        )

    def test_get_redirect_url_defaults_and_rejects_evil_return(self):
        # Act
        success = self.service.get_redirect_url(
            return_url="http://localhost:3000/settings?x=1"
        )
        evil = self.service.get_redirect_url(return_url="https://evil.com/phish")

        # Assert
        self.assertIn("gmail=connected", success)
        self.assertIn("x=1", success)
        self.assertNotIn("evil.com", evil)
        self.assertIn("expert-finder/settings", evil)
