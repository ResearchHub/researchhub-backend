from unittest.mock import Mock, patch

import requests
from allauth.socialaccount.models import SocialApp, SocialToken
from django.contrib.sites.models import Site
from django.test import RequestFactory, TestCase
from rest_framework import serializers

from oauth.adapters import TwitterOAuth2Adapter


class TwitterOAuth2AdapterTests(TestCase):
    def setUp(self):
        self.app = SocialApp.objects.create(
            provider="twitter_oauth2",
            name="X",
            client_id="test-id",
            secret="test-secret",
        )
        self.app.sites.add(Site.objects.get_current())
        self.request = RequestFactory().get("/")
        self.adapter = TwitterOAuth2Adapter(self.request)
        self.token = SocialToken(token="test-token")

    @staticmethod
    def _mock_profile(mock_get: Mock, **fields: str) -> None:
        mock_get.return_value.json.return_value = {
            "data": {"id": "123", "name": "X User", "username": "xuser", **fields}
        }

    @patch.object(requests.Session, "get")
    def test_complete_login_requests_confirmed_email_from_x(self, mock_get):
        """
        Test that the X profile request asks for the user's confirmed email.
        """
        # Arrange
        self._mock_profile(mock_get, confirmed_email="user@example.com")

        # Act
        self.adapter.complete_login(self.request, self.app, self.token)

        # Assert
        mock_get.assert_called_once()
        user_fields = mock_get.call_args.kwargs["params"]["user.fields"].split(",")
        self.assertIn("confirmed_email", user_fields)

    @patch.object(requests.Session, "get")
    def test_complete_login_uses_confirmed_email_as_verified_address(self, mock_get):
        """
        Test that the confirmed email becomes the user's verified primary email.
        """
        # Arrange
        self._mock_profile(mock_get, confirmed_email="User@Example.com")

        # Act
        login = self.adapter.complete_login(self.request, self.app, self.token)

        # Assert
        self.assertEqual(login.user.email, "user@example.com")
        self.assertEqual(len(login.email_addresses), 1)
        self.assertEqual(login.email_addresses[0].email, "user@example.com")
        self.assertTrue(login.email_addresses[0].primary)
        self.assertTrue(login.email_addresses[0].verified)

    @patch.object(requests.Session, "get")
    def test_complete_login_rejects_missing_confirmed_email(self, mock_get):
        """
        Test that X logins without a confirmed email are rejected.
        """
        # Arrange
        self._mock_profile(mock_get)

        # Act & Assert
        with self.assertRaises(serializers.ValidationError) as context:
            self.adapter.complete_login(self.request, self.app, self.token)
        self.assertIn("confirmed_email", context.exception.detail)
