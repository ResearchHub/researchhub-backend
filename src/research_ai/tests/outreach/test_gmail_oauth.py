from unittest.mock import Mock

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.test import TestCase, override_settings

from research_ai.models import OutreachMailboxConnection
from research_ai.services.outreach.gmail_oauth import (
    GmailMailboxNotAllowedError,
    GmailOAuthError,
    GmailOAuthRedirectUriError,
    GmailOAuthService,
    get_google_oauth_credentials,
    is_allowed_oauth_redirect_uri,
)
from user.tests.helpers import create_random_default_user

_FE_REDIRECT = "http://localhost:3000/expert-finder/settings"


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
    GMAIL_OUTREACH_REDIRECT_URI=_FE_REDIRECT,
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

    def test_get_connect_params_returns_offline_access_and_consent_prompt(self):
        # Act
        payload = self.service.get_connect_params()

        # Assert
        self.assertEqual(payload["client_id"], "google-client-id")
        self.assertEqual(payload["redirect_uri"], _FE_REDIRECT)
        self.assertEqual(payload["access_type"], "offline")
        self.assertEqual(payload["prompt"], "consent")
        self.assertIn("https://www.googleapis.com/auth/gmail.send", payload["scopes"])
        self.assertIn(
            "https://www.googleapis.com/auth/gmail.readonly", payload["scopes"]
        )
        self.assertIn("openid", payload["scopes"])
        self.assertIn("email", payload["scopes"])

    def test_is_allowed_oauth_redirect_uri_accepts_configured_and_cors(self):
        # Assert
        self.assertTrue(is_allowed_oauth_redirect_uri(_FE_REDIRECT))
        self.assertTrue(
            is_allowed_oauth_redirect_uri("http://localhost:3000/expert-finder/other")
        )
        self.assertTrue(
            is_allowed_oauth_redirect_uri("https://researchhub.com/settings")
        )
        self.assertFalse(is_allowed_oauth_redirect_uri("https://evil.com/phish"))
        self.assertFalse(is_allowed_oauth_redirect_uri(""))
        self.assertFalse(is_allowed_oauth_redirect_uri(None))

    def test_connect_with_code_accepts_gmail_com(self):
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

        # Act
        result = self.service.connect_with_code(
            user, code="auth-code", redirect_uri=_FE_REDIRECT
        )

        # Assert
        self.assertTrue(result["connected"])
        self.assertEqual(result["email"], "editor@gmail.com")
        self.assertEqual(result["status"], OutreachMailboxConnection.Status.ACTIVE)
        connection = OutreachMailboxConnection.objects.get(user=user)
        self.assertEqual(connection.email, "editor@gmail.com")
        self.assertEqual(connection.access_token, "access-1")
        self.assertEqual(connection.refresh_token, "refresh-1")
        self.mock_client.exchange_code_for_token.assert_called_once()
        call_kwargs = self.mock_client.exchange_code_for_token.call_args.kwargs
        self.assertEqual(call_kwargs["redirect_uri"], _FE_REDIRECT)
        self.assertEqual(call_kwargs["code"], "auth-code")

    def test_connect_with_code_accepts_googlemail_com(self):
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

        # Act
        result = self.service.connect_with_code(
            user, code="auth-code", redirect_uri=_FE_REDIRECT
        )

        # Assert
        self.assertEqual(result["email"], "user@googlemail.com")
        self.assertEqual(
            OutreachMailboxConnection.objects.get(user=user).email,
            "user@googlemail.com",
        )

    def test_connect_with_code_rejects_researchhub_foundation(self):
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

        # Act / Assert
        with self.assertRaises(GmailMailboxNotAllowedError):
            self.service.connect_with_code(
                user, code="auth-code", redirect_uri=_FE_REDIRECT
            )
        self.assertFalse(OutreachMailboxConnection.objects.filter(user=user).exists())

    def test_connect_with_code_rejects_researchhub_com(self):
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

        # Act / Assert
        with self.assertRaises(GmailMailboxNotAllowedError):
            self.service.connect_with_code(
                user, code="auth-code", redirect_uri=_FE_REDIRECT
            )
        self.assertFalse(OutreachMailboxConnection.objects.filter(user=user).exists())

    def test_connect_with_code_rejects_evil_redirect_uri(self):
        # Arrange
        user = create_random_default_user("evil_redirect")

        # Act / Assert
        with self.assertRaises(GmailOAuthRedirectUriError):
            self.service.connect_with_code(
                user,
                code="auth-code",
                redirect_uri="https://evil.com/phish",
            )
        self.mock_client.exchange_code_for_token.assert_not_called()

    def test_connect_with_code_rejects_missing_code(self):
        # Arrange
        user = create_random_default_user("missing_code")

        # Act / Assert
        with self.assertRaises(GmailOAuthError):
            self.service.connect_with_code(user, code="", redirect_uri=_FE_REDIRECT)

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
                "daily_cap": payload["daily_cap"],
                "sent_today": 0,
                "queued_today": 0,
                "remaining_today": payload["remaining_today"],
                "resets_at": payload["resets_at"],
            },
        )
        self.assertEqual(payload["daily_cap"], payload["remaining_today"])
        self.assertIn("T", payload["resets_at"])
