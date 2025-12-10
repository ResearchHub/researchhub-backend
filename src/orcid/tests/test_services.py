from unittest.mock import Mock, patch

from allauth.socialaccount.models import SocialAccount, SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.test import TestCase

from orcid.services.orcid_service import (
    ORCID_BASE_URL,
    build_auth_url,
    connect_orcid_account,
    exchange_code_for_token,
    get_orcid_app,
    is_orcid_connected,
)
from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_default_user


class OrcidServiceTests(TestCase):
    def test_is_connected_returns_false_for_none(self):
        self.assertFalse(is_orcid_connected(None))

    def test_is_connected_returns_true_when_linked(self):
        user = create_random_default_user("linked")
        SocialAccount.objects.create(user=user, provider=OrcidProvider.id, uid="123")
        self.assertTrue(is_orcid_connected(user))

    def test_get_app_returns_app(self):
        app = create_orcid_app()
        self.assertEqual(get_orcid_app(), app)

    def test_get_app_raises_when_missing(self):
        with self.assertRaises(SocialApp.DoesNotExist):
            get_orcid_app()

    def test_build_auth_url(self):
        app = create_orcid_app()
        url = build_auth_url(app, 123)
        self.assertIn("test-id", url)
        self.assertIn("123", url)

    def test_connect_creates_account(self):
        user = create_random_default_user("new")
        connect_orcid_account(user, {"orcid": "0000-0001-2345-6789"})
        self.assertTrue(SocialAccount.objects.filter(user=user).exists())

    def test_connect_updates_author(self):
        user = create_random_default_user("author")
        connect_orcid_account(user, {"orcid": "0000-0001-2345-6789"})
        user.author_profile.refresh_from_db()
        self.assertEqual(user.author_profile.orcid_id, f"{ORCID_BASE_URL}/0000-0001-2345-6789")

    def test_connect_raises_on_invalid_response(self):
        user = create_random_default_user("invalid")
        with self.assertRaises(ValueError):
            connect_orcid_account(user, {})

    def test_connect_raises_when_already_linked(self):
        user1 = create_random_default_user("user1")
        user2 = create_random_default_user("user2")
        SocialAccount.objects.create(
            user=user1, provider=OrcidProvider.id, uid="0000-0001-2345-6789"
        )
        with self.assertRaises(ValueError):
            connect_orcid_account(user2, {"orcid": "0000-0001-2345-6789"})

    @patch("orcid.services.orcid_service.requests.post")
    def test_exchange_code(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {"orcid": "123"}, raise_for_status=Mock())
        app = create_orcid_app()
        result = exchange_code_for_token(app, "code")
        self.assertEqual(result["orcid"], "123")
