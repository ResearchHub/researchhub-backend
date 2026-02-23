from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from purchase.circle import webhook


class TestCircleWebhookHelpers(TestCase):
    def setUp(self):
        cache.clear()

    @patch("purchase.circle.webhook._fetch_public_key", return_value="Zm9v")
    def test_get_public_key_accepts_uppercase_uuid(self, mock_fetch_public_key):
        key_id = "05B3F4E5-EC27-44B8-AA40-3698577F6D92"

        public_key = webhook._get_public_key_b64(key_id)

        self.assertEqual(public_key, "Zm9v")
        mock_fetch_public_key.assert_called_once_with(key_id)

    @patch(
        "purchase.circle.webhook._fetch_token",
        return_value={"tokenAddress": "0xabc", "blockchain": "BASE"},
    )
    def test_get_token_accepts_uppercase_uuid(self, mock_fetch_token):
        token_id = "38F2AD29-A77B-5A44-BE05-8D03923878A2"

        token = webhook._get_token(token_id)

        self.assertEqual(token["tokenAddress"], "0xabc")
        mock_fetch_token.assert_called_once_with(token_id)

    def test_get_public_key_rejects_non_uuid(self):
        with self.assertRaises(ValueError):
            webhook._get_public_key_b64("NOT-A-UUID")

    def test_get_token_rejects_non_uuid(self):
        with self.assertRaises(ValueError):
            webhook._get_token("token-rsc")
