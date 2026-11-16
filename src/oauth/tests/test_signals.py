import uuid
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from allauth.account.signals import user_signed_up
from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_grant_model,
    get_refresh_token_model,
)

import oauth.signals  # noqa: F401 - register signals
from oauth.models import DelegatedAccessToken
from user.tests.helpers import create_random_default_user

AccessToken = get_access_token_model()
Application = get_application_model()
Grant = get_grant_model()
RefreshToken = get_refresh_token_model()

API_RESOURCE = "https://api.example.com"
MCP_RESOURCE = "https://mcp.example.com/v1/mcp"
REDIRECT_URI = "http://127.0.0.1:33418/callback"


class UserSignupSignalTests(TestCase):
    """
    Tests the signals for user signup handling.
    """

    def setUp(self):
        self.user = create_random_default_user("signal_test")
        self.mock_request = Mock()

    @patch("oauth.signals.UserSignupService")
    def test_handle_user_signup_adds_to_mailchimp(self, mock_service_class):
        """
        Tests that the user is added to Mailchimp on signup.
        """
        # Arrange
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Act
        user_signed_up.send(
            sender=self.__class__, request=self.mock_request, user=self.user
        )

        # Assert
        mock_service.add_to_mailchimp.assert_called_once_with(self.user)

    @patch("oauth.signals.UserSignupService")
    def test_handle_user_signup_tracks_signup(self, mock_service_class):
        """
        Tests that the signup is tracked in Amplitude on user signup.
        """
        # Arrange
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Act
        user_signed_up.send(
            sender=self.__class__, request=self.mock_request, user=self.user
        )

        # Assert
        mock_service.track_signup.assert_called_once()
        call_args = mock_service.track_signup.call_args
        self.assertEqual(call_args[0][0], self.mock_request)
        self.assertEqual(call_args[0][1], self.user)


@override_settings(OAUTH_ENABLED=True)
class UserDeactivationSignalTests(TestCase):
    """
    Tests that deactivating a user revokes their OAuth tokens.
    """

    def setUp(self):
        self.user = create_random_default_user("oauth_deactivation")
        self.application = Application.objects.create(
            name="AIApp1",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
        )

    def _create_tokens(self, user, name):
        access_token = AccessToken.objects.create(
            user=user,
            application=self.application,
            token=f"{name}-access",
            expires=timezone.now() + timedelta(hours=1),
            scope="read",
            resource=[MCP_RESOURCE],
        )
        RefreshToken.objects.create(
            user=user,
            application=self.application,
            token=f"{name}-refresh",
            access_token=access_token,
            token_family=uuid.uuid4(),
        )
        Grant.objects.create(
            user=user,
            application=self.application,
            code=f"{name}-code",
            expires=timezone.now() + timedelta(minutes=1),
            redirect_uri=REDIRECT_URI,
            scope="read",
        )
        return access_token

    def _refresh(self, refresh_token):
        params = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.application.client_id,
        }
        return self.client.post(
            "/oauth/token/",
            urlencode(params),
            content_type="application/x-www-form-urlencoded",
        )

    @staticmethod
    def _set_active(user, is_active):
        user.is_active = is_active
        user.save()

    def test_deactivated_user_cannot_refresh(self):
        # Arrange
        self._create_tokens(self.user, "user")
        self._set_active(self.user, False)

        # Act
        response = self._refresh("user-refresh")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_reactivated_user_cannot_refresh_tokens_from_before_deactivation(self):
        # Arrange
        self._create_tokens(self.user, "user")
        self._set_active(self.user, False)
        self._set_active(self.user, True)

        # Act
        response = self._refresh("user-refresh")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_deactivation_deletes_access_tokens_and_authorization_codes(self):
        # Arrange
        mcp_token = self._create_tokens(self.user, "user")
        api_token = AccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="user-api",
            expires=timezone.now() + timedelta(minutes=5),
            scope="read",
            resource=[API_RESOURCE],
        )
        DelegatedAccessToken.objects.create(
            access_token=api_token, source_token=mcp_token
        )

        # Act
        self._set_active(self.user, False)

        # Assert
        self.assertFalse(AccessToken.objects.filter(user=self.user).exists())
        self.assertFalse(Grant.objects.filter(user=self.user).exists())

    def test_deactivation_keeps_other_users_tokens(self):
        # Arrange
        other_user = create_random_default_user("oauth_other")
        self._create_tokens(other_user, "other")

        # Act
        self._set_active(self.user, False)

        # Assert
        self.assertTrue(AccessToken.objects.filter(user=other_user).exists())
        self.assertTrue(
            RefreshToken.objects.filter(user=other_user, revoked__isnull=True).exists()
        )
        self.assertTrue(Grant.objects.filter(user=other_user).exists())

    def test_saving_an_active_user_keeps_their_tokens(self):
        # Arrange
        self._create_tokens(self.user, "user")
        self.user.first_name = "Renamed"
        self.user.save()

        # Act
        response = self._refresh("user-refresh")

        # Assert
        self.assertEqual(response.status_code, 200)
