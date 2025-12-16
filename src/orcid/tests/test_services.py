from unittest.mock import Mock, patch

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
    def test_exchange_code_for_token(self, mock_post):
        create_orcid_app()
        mock_post.return_value = Mock(json=lambda: {"orcid": "0000-0001-2345-6789"}, raise_for_status=Mock())

        result = self.service.exchange_code_for_token("auth_code")

        self.assertEqual(result["orcid"], "0000-0001-2345-6789")

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
        user1 = create_random_default_user("user1")
        user2 = create_random_default_user("user2")
        create_orcid_app()

        with self.assertRaises(ValueError):
            self.service.connect_orcid_account(user1, {})

        SocialAccount.objects.create(user=user1, provider=OrcidProvider.id, uid="0000-0001-2345-6789")
        with self.assertRaises(ValueError):
            self.service.connect_orcid_account(user2, {"orcid": "0000-0001-2345-6789"})

    def test_decode_state(self):
        encoded = self.service._encode_signed_value({"user_id": 123})
        self.assertEqual(self.service.decode_state(encoded)["user_id"], 123)

        self.assertIsNone(self.service.decode_state("invalid"))

        self.service.STATE_MAX_AGE = 0
        self.assertIsNone(self.service.decode_state(encoded))

    def test_get_redirect_url(self):
        self.assertEqual(
            self.service.get_redirect_url(return_url="https://researchhub.com"),
            "https://researchhub.com?orcid_connected=true"
        )
        self.assertEqual(
            self.service.get_redirect_url(error="failed", return_url="https://researchhub.com?tab=1"),
            "https://researchhub.com?tab=1&orcid_error=failed"
        )
        self.assertNotIn("evil.com", self.service.get_redirect_url(return_url="https://evil.com"))
