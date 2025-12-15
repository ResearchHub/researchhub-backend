from unittest.mock import Mock, patch

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.test import TestCase

from orcid.services.orcid_service import (
    ORCID_BASE_URL,
    build_auth_url,
    connect_orcid_account,
    decode_state,
    exchange_code_for_token,
    get_orcid_app,
    get_redirect_url,
    is_orcid_connected,
    is_valid_redirect_url,
)
from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_default_user
from utils.signer import encode_signed_value


class OrcidServiceTests(TestCase):
    def test_is_connected(self):
        self.assertFalse(is_orcid_connected(None))
        user = create_random_default_user("linked")
        self.assertFalse(is_orcid_connected(user))
        SocialAccount.objects.create(user=user, provider=OrcidProvider.id, uid="123")
        self.assertTrue(is_orcid_connected(user))

    def test_get_app(self):
        with self.assertRaises(SocialApp.DoesNotExist):
            get_orcid_app()
        app = create_orcid_app()
        self.assertEqual(get_orcid_app(), app)

    def test_state_encoding(self):
        data = {"user_id": 123, "return_url": "http://example.com"}
        self.assertEqual(decode_state(encode_signed_value(data)), data)
        self.assertIsNone(decode_state("invalid"))
        self.assertIsNone(decode_state(""))

    @patch("orcid.services.orcid_service.STATE_MAX_AGE", 0)
    def test_state_expiry(self):
        self.assertIsNone(decode_state(encode_signed_value({"user_id": 123})))

    def test_build_auth_url(self):
        app = create_orcid_app()
        url = build_auth_url(app, 123, "https://researchhub.com/settings")
        self.assertIn("test-id", url)
        self.assertIn("state=", url)

    def test_connect_creates_account_and_token(self):
        user, app = create_random_default_user("new"), create_orcid_app()
        token_data = {"orcid": "0000-0001-2345-6789", "access_token": "a", "refresh_token": "r", "expires_in": 3600}
        connect_orcid_account(user, token_data, app)

        self.assertTrue(SocialAccount.objects.filter(user=user).exists())
        token = SocialToken.objects.get(account__user=user)
        self.assertEqual((token.token, token.token_secret), ("a", "r"))

    def test_connect_updates_author(self):
        user, app = create_random_default_user("author"), create_orcid_app()
        connect_orcid_account(user, {"orcid": "0000-0001-2345-6789"}, app)
        user.author_profile.refresh_from_db()
        self.assertEqual(user.author_profile.orcid_id, f"{ORCID_BASE_URL}/0000-0001-2345-6789")

    def test_connect_raises_errors(self):
        user1, user2, app = create_random_default_user("u1"), create_random_default_user("u2"), create_orcid_app()
        with self.assertRaises(ValueError):
            connect_orcid_account(user1, {}, app)
        SocialAccount.objects.create(user=user1, provider=OrcidProvider.id, uid="0000-0001-2345-6789")
        with self.assertRaises(ValueError):
            connect_orcid_account(user2, {"orcid": "0000-0001-2345-6789"}, app)

    @patch("orcid.services.orcid_service.requests.post")
    def test_exchange_code(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {"orcid": "123"}, raise_for_status=Mock())
        self.assertEqual(exchange_code_for_token(create_orcid_app(), "code")["orcid"], "123")

    def test_get_redirect_url(self):
        cases = [
            ({"return_url": "https://researchhub.com/funds"}, "https://researchhub.com/funds?orcid_connected=true"),
            ({"return_url": "https://researchhub.com?tab=1"}, "https://researchhub.com?tab=1&orcid_connected=true"),
            ({"error": "x", "return_url": "https://researchhub.com"}, "https://researchhub.com?orcid_error=x"),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(get_redirect_url(**kwargs), expected)

    def test_get_redirect_url_rejects_invalid(self):
        url = get_redirect_url(return_url="https://evil.com")
        self.assertNotIn("evil.com", url)

    def test_is_valid_redirect_url(self):
        valid = ["https://researchhub.com/x", "https://www.researchhub.com/x", "http://localhost:3000/x"]
        invalid = ["https://evil.com", "javascript:alert(1)", None, ""]
        for url in valid:
            self.assertTrue(is_valid_redirect_url(url), f"{url} should be valid")
        for url in invalid:
            self.assertFalse(is_valid_redirect_url(url), f"{url} should be invalid")
