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

    def test_get_public_key_rejects_non_uuid(self):
        with self.assertRaises(ValueError):
            webhook._get_public_key_b64("NOT-A-UUID")

    def test_is_rsc_token_recognises_known_ids(self):
        for blockchain, token_id in webhook._RSC_TOKEN_ID_BY_BLOCKCHAIN.items():
            self.assertTrue(webhook.is_rsc_token(token_id, blockchain))

    def test_is_rsc_token_rejects_unknown_id(self):
        self.assertFalse(webhook.is_rsc_token("unknown-token-id", "BASE"))

    def test_is_rsc_token_rejects_wrong_blockchain(self):
        """A valid token ID on the wrong blockchain should be rejected."""
        token_id = webhook._RSC_TOKEN_ID_BY_BLOCKCHAIN["BASE"]
        self.assertFalse(webhook.is_rsc_token(token_id, "ETH"))
