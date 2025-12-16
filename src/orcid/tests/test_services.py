from unittest.mock import Mock, patch

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.test import TestCase

from orcid.services.orcid_service import OrcidService
from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_default_user


class OrcidServiceTests(TestCase):
    def setUp(self):
        self.service = OrcidService()

    def test_build_auth_url(self):
        create_orcid_app()

        url = self.service.build_auth_url(123, "https://researchhub.com/settings")
        self.assertIn("test-id", url)
        self.assertIn("state=", url)

        url_no_return = self.service.build_auth_url(123)
        self.assertIn("oauth/authorize", url_no_return)

    @patch("orcid.services.orcid_service.requests.post")
    def test_process_callback_success(self, mock_post):
        user = create_random_default_user("test_user")
        create_orcid_app()
        mock_post.return_value = Mock(
            json=lambda: {"orcid": "0000-0001-2345-6789", "access_token": "token"},
            raise_for_status=Mock()
        )
        state = self.service._encode_signed_value({"user_id": user.id, "return_url": "https://researchhub.com/profile"})

        result = self.service.process_callback("auth_code", state)

        self.assertIn("orcid_connected=true", result)
        self.assertIn("researchhub.com/profile", result)
        self.assertTrue(SocialAccount.objects.filter(user=user).exists())

    def test_process_callback_invalid_state(self):
        create_orcid_app()

        result = self.service.process_callback("code", "invalid_state")

        self.assertIn("orcid_error=invalid_state", result)

    def test_process_callback_user_not_found(self):
        create_orcid_app()
        state = self.service._encode_signed_value({"user_id": 99999})

        result = self.service.process_callback("code", state)

        self.assertIn("orcid_error=invalid_state", result)

    @patch("orcid.services.orcid_service.requests.post")
    def test_process_callback_already_linked(self, mock_post):
        user1 = create_random_default_user("user1")
        user2 = create_random_default_user("user2")
        create_orcid_app()
        SocialAccount.objects.create(user=user1, provider=OrcidProvider.id, uid="0000-0001-2345-6789")
        mock_post.return_value = Mock(
            json=lambda: {"orcid": "0000-0001-2345-6789"},
            raise_for_status=Mock()
        )
        state = self.service._encode_signed_value({"user_id": user2.id})

        result = self.service.process_callback("code", state)

        self.assertIn("orcid_error=already_linked", result)

    @patch("orcid.services.orcid_service.requests.post")
    def test_process_callback_service_error(self, mock_post):
        user = create_random_default_user("user")
        create_orcid_app()
        mock_post.side_effect = requests.RequestException()
        state = self.service._encode_signed_value({"user_id": user.id})

        self.assertIn("orcid_error=service_error", self.service.process_callback("code", state))

    def test_connect_creates_account_token_and_updates_author(self):
        user = create_random_default_user("test_user")
        create_orcid_app()
        token_data = {"orcid": "0000-0001-2345-6789", "access_token": "token", "refresh_token": "refresh", "expires_in": 3600}

        self.service.connect_orcid_account(user, token_data)

        self.assertTrue(SocialAccount.objects.filter(user=user, provider=OrcidProvider.id).exists())
        self.assertEqual(SocialToken.objects.get(account__user=user).token, "token")
        user.author_profile.refresh_from_db()
        self.assertIn("0000-0001-2345-6789", user.author_profile.orcid_id)

    def test_connect_raises_on_invalid_data(self):
        user = create_random_default_user("user1")
        create_orcid_app()

        with self.assertRaises(ValueError):
            self.service.connect_orcid_account(user, {})

    def test_decode_state(self):
        encoded = self.service._encode_signed_value({"user_id": 123})
        self.assertEqual(self.service.decode_state(encoded)["user_id"], 123)
        self.assertIsNone(self.service.decode_state("invalid"))

    def test_get_redirect_url(self):
        self.assertIn("orcid_connected=true", self.service.get_redirect_url(return_url="https://researchhub.com"))
        self.assertIn("orcid_error=failed", self.service.get_redirect_url(error="failed"))
        self.assertNotIn("evil.com", self.service.get_redirect_url(return_url="https://evil.com"))
