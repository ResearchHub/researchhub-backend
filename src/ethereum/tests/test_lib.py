from unittest.mock import Mock, call, patch

from django.conf import settings
from django.test import TestCase, override_settings

from ethereum.lib import convert_reputation_amount_to_token_amount, get_private_key


class EthereumLibTests(TestCase):
    def setUp(self):
        self.token_ticker = "RSC"

    def test_convert_reputation_amount_to_token_amount(self):
        rep = 1
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker, rep
        )
        self.assertEqual(integer, 1000000000000000000)
        self.assertEqual(decimal, "1.0")
        rep = 12
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker, rep
        )
        self.assertEqual(integer, 12000000000000000000)
        self.assertEqual(decimal, "12.0")
        rep = 210
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker, rep
        )
        self.assertEqual(integer, 210000000000000000000)
        self.assertEqual(decimal, "210.0")

    def test_convert_reputation_amount_to_token_amount_with_negatives(self):
        rep = -5
        with self.assertRaises(ValueError):
            convert_reputation_amount_to_token_amount(self.token_ticker, rep)

    @override_settings(
        WEB3_KEYSTORE_SECRET_ID="researchhub-web3-keystore",
        WEB3_KEYSTORE_PASSWORD_SECRET_ID="researchhub-web3-keystore-password",
    )
    @patch("ethereum.lib.create_client")
    @patch("ethereum.lib.web3_provider.ethereum")
    def test_get_private_key(self, mock_w3_ethereum, mock_create_client):
        # Arrange
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        secrets = {
            "researchhub-web3-keystore": {"SecretString": "mock_keystore"},
            "researchhub-web3-keystore-password": {"SecretString": "mock_password"},
        }
        mock_client.get_secret_value.side_effect = lambda SecretId: secrets[SecretId]

        mock_private_key = "mock_private_key"
        mock_w3_ethereum.eth.account.decrypt.return_value = mock_private_key

        # Act
        actual = get_private_key()

        # Assert
        mock_create_client.assert_called_once_with("secretsmanager")
        mock_client.get_secret_value.assert_has_calls(
            [
                call(SecretId="researchhub-web3-keystore"),
                call(SecretId="researchhub-web3-keystore-password"),
            ]
        )
        mock_w3_ethereum.eth.account.decrypt.assert_called_with(
            "mock_keystore", "mock_password"
        )
        self.assertEqual(actual, mock_private_key)
