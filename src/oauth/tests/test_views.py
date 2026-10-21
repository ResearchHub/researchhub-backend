from unittest.mock import patch

import requests
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error
from django.contrib.sites.models import Site
from rest_framework.test import APITestCase

from oauth.services.user_signup_service import UserSignupService
from user.models import User


@patch.object(UserSignupService, "track_signup")
@patch.object(requests.Session, "get")
@patch.object(OAuth2Client, "get_access_token")
class XLoginViewTests(APITestCase):
    url = "/api/auth/x/login/"
    payload = {
        "code": "auth-code",
        "code_verifier": "v" * 43,
        "redirect_uri": "https://www.researchhub.com/api/auth/callback/x",
    }

    def setUp(self):
        app = SocialApp.objects.create(
            provider="twitter_oauth2",
            provider_id="x_oauth2",
            name="X",
            client_id="test-id",
            secret="test-secret",
        )
        app.sites.add(Site.objects.get_current())

    @staticmethod
    def _mock_profile(mock_get, **fields):
        mock_get.return_value.json.return_value = {
            "data": {
                "id": "123",
                "name": "X User",
                "username": "xuser",
                "profile_image_url": "https://pbs.twimg.com/xuser.jpg",
                **fields,
            }
        }

    def test_login_creates_user_from_x_profile(
        self, mock_exchange, mock_get, mock_track
    ):
        """
        Test that X login exchanges the code, signs the user up with the confirmed
        email, and populates the author profile from X.
        """
        # Arrange
        mock_exchange.return_value = {"access_token": "x-token"}
        self._mock_profile(mock_get, confirmed_email="User@Example.com")

        # Act
        response = self.client.post(self.url, self.payload)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["access_token"], "x-token")
        self.assertIn("key", response.data)
        mock_exchange.assert_called_once_with("auth-code", pkce_code_verifier="v" * 43)
        user_fields = mock_get.call_args.kwargs["params"]["user.fields"].split(",")
        self.assertIn("confirmed_email", user_fields)

        user = User.objects.get(email="user@example.com")
        self.assertTrue(user.emailaddress_set.get(primary=True).verified)
        self.assertTrue(user.socialaccount_set.filter(provider="x_oauth2").exists())
        self.assertEqual(user.author_profile.twitter, "https://x.com/xuser")
        self.assertEqual(
            user.author_profile.profile_image, "https://pbs.twimg.com/xuser.jpg"
        )

    def test_login_rejects_failed_code_exchange(
        self, mock_exchange, mock_get, mock_track
    ):
        """
        Test that a failed X authorization code exchange is rejected.
        """
        # Arrange
        mock_exchange.side_effect = OAuth2Error("invalid_grant")

        # Act
        response = self.client.post(self.url, self.payload)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.data)
        mock_get.assert_not_called()

    def test_login_rejects_missing_confirmed_email(
        self, mock_exchange, mock_get, mock_track
    ):
        """
        Test that X logins without a confirmed email are rejected.
        """
        # Arrange
        mock_exchange.return_value = {"access_token": "x-token"}
        self._mock_profile(mock_get)

        # Act
        response = self.client.post(self.url, self.payload)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirmed_email", response.data)
        self.assertFalse(User.objects.filter(username="xuser").exists())
