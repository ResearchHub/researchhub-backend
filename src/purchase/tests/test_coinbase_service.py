import os
import uuid
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

import requests
from django.test import override_settings

from purchase.services.coinbase_service import CoinbaseService


class TestCoinbaseService(TestCase):
    """Test cases for CoinbaseService."""

    @override_settings(
        COINBASE_API_KEY_ID="test_key_id",
        COINBASE_API_KEY_SECRET="test_key_secret",
    )
    def setUp(self):
        """Set up test environment."""
        self.service = CoinbaseService()

    def test_initialization_with_credentials(self):
        """Test service initialization with credentials."""
        self.assertEqual(self.service.api_key_id, "test_key_id")
        self.assertEqual(self.service.api_key_secret, "test_key_secret")

    @override_settings(COINBASE_API_KEY_ID=None, COINBASE_API_KEY_SECRET=None)
    def test_initialization_without_credentials(self):
        """Test service initialization without credentials."""
        with self.assertLogs(
            "purchase.services.coinbase_service", level="WARNING"
        ) as cm:
            CoinbaseService()
            self.assertIn("Coinbase API credentials not configured", cm.output[0])

    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_generate_jwt_token(self, mock_generate_jwt):
        """Test JWT token generation."""
        mock_generate_jwt.return_value = "test_jwt_token"

        token = self.service.generate_jwt_token(
            request_method="GET",
            request_host="api.coinbase.com",
            request_path="/v2/user",
            expires_in=120,
        )

        self.assertEqual(token, "test_jwt_token")
        mock_generate_jwt.assert_called_once()

        # Verify the JwtOptions were created with correct parameters
        call_args = mock_generate_jwt.call_args[0][0]
        self.assertEqual(call_args.api_key_id, "test_key_id")
        self.assertEqual(call_args.api_key_secret, "test_key_secret")
        self.assertEqual(call_args.request_method, "GET")
        self.assertEqual(call_args.request_host, "api.coinbase.com")
        self.assertEqual(call_args.request_path, "/v2/user")
        self.assertEqual(call_args.expires_in, 120)

    @override_settings(COINBASE_API_KEY_ID=None, COINBASE_API_KEY_SECRET=None)
    def test_generate_jwt_token_without_credentials(self):
        """Test JWT token generation without credentials raises error."""
        service = CoinbaseService()

        with self.assertRaises(ValueError) as context:
            service.generate_jwt_token(
                request_method="GET",
                request_host="api.coinbase.com",
                request_path="/v2/user",
            )

        self.assertIn("Coinbase API credentials not configured", str(context.exception))

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_create_session_token_success(self, mock_generate_jwt, mock_post):
        """Test successful session token creation."""
        mock_generate_jwt.return_value = "test_jwt_token"

        # Mock successful API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "token": uuid.uuid4().hex,
            "channelId": "channel_123",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        addresses = [{"address": "0x123456789", "blockchains": ["base", "ethereum"]}]
        assets = ["USDC", "ETH"]

        result = self.service.create_session_token(addresses=addresses, assets=assets)

        # Verify the result
        self.assertIn("token", result)
        self.assertEqual(result["channelId"], "channel_123")

        # Verify JWT generation was called
        mock_generate_jwt.assert_called_once()

        # Verify the API request
        mock_post.assert_called_once_with(
            "https://api.developer.coinbase.com/onramp/v1/token",
            headers={
                "Authorization": "Bearer test_jwt_token",
                "Content-Type": "application/json",
            },
            json={
                "addresses": addresses,
                "assets": assets,
            },
            timeout=30,
        )

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_create_session_token_without_assets(self, mock_generate_jwt, mock_post):
        """Test session token creation without assets restriction."""
        mock_generate_jwt.return_value = "test_jwt_token"

        mock_response = Mock()
        mock_response.json.return_value = {
            "token": uuid.uuid4().hex,
            "channelId": "channel_456",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        addresses = [{"address": "0x987654321", "blockchains": ["base"]}]

        result = self.service.create_session_token(addresses=addresses)

        # Verify the request body doesn't include assets
        call_args = mock_post.call_args
        request_body = call_args[1]["json"]
        self.assertNotIn("assets", request_body)
        self.assertEqual(request_body["addresses"], addresses)

    @override_settings(COINBASE_API_KEY_ID=None, COINBASE_API_KEY_SECRET=None)
    def test_create_session_token_without_credentials(self):
        """Test session token creation without API credentials."""
        service = CoinbaseService()

        with self.assertRaises(ValueError) as context:
            service.create_session_token(
                addresses=[{"address": "0x123", "blockchains": ["base"]}]
            )

        self.assertIn("Coinbase API credentials not configured", str(context.exception))

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_create_session_token_api_error(self, mock_generate_jwt, mock_post):
        """Test session token creation with API error."""
        mock_generate_jwt.return_value = "test_jwt_token"

        # Mock API error response
        mock_post.side_effect = requests.RequestException("API Error")

        addresses = [{"address": "0x123456789", "blockchains": ["base"]}]

        with self.assertRaises(requests.RequestException):
            self.service.create_session_token(addresses=addresses)

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_create_session_token_http_error(self, mock_generate_jwt, mock_post):
        """Test session token creation with HTTP error status."""
        mock_generate_jwt.return_value = "test_jwt_token"

        # Mock HTTP error response
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "400 Bad Request"
        )
        mock_post.return_value = mock_response

        addresses = [{"address": "0x123456789", "blockchains": ["base"]}]

        with self.assertRaises(requests.HTTPError):
            self.service.create_session_token(addresses=addresses)

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_generate_onramp_url_success(self, mock_generate_jwt, mock_post):
        """Test successful onramp URL generation."""
        mock_generate_jwt.return_value = "test_jwt_token"

        # Mock successful API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "token": uuid.uuid4().hex,
            "channelId": "channel_789",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        addresses = [{"address": "0xABC123", "blockchains": ["base", "ethereum"]}]

        result = self.service.generate_onramp_url(
            addresses=addresses,
            assets=["ETH", "USDC"],
            default_network="base",
            preset_fiat_amount=100,
            default_asset="ETH",
        )

        # Verify the URL format
        self.assertIn("https://pay.coinbase.com/buy/select-asset", result)
        self.assertIn("sessionToken=", result)
        self.assertIn("defaultNetwork=base", result)
        self.assertIn("presetFiatAmount=100", result)
        self.assertIn("defaultAsset=ETH", result)

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_generate_onramp_url_minimal(self, mock_generate_jwt, mock_post):
        """Test onramp URL generation with minimal parameters."""
        mock_generate_jwt.return_value = "test_jwt_token"

        mock_response = Mock()
        mock_response.json.return_value = {
            "token": uuid.uuid4().hex,
            "channelId": "channel_minimal",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        addresses = [{"address": "0xDEF456", "blockchains": ["ethereum"]}]

        result = self.service.generate_onramp_url(addresses=addresses)

        # Verify minimal URL format
        self.assertIn("https://pay.coinbase.com/buy/select-asset?sessionToken=", result)

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_generate_onramp_url_with_crypto_amount(self, mock_generate_jwt, mock_post):
        """Test onramp URL generation with preset crypto amount."""
        mock_generate_jwt.return_value = "test_jwt_token"

        mock_response = Mock()
        mock_response.json.return_value = {
            "token": uuid.uuid4().hex,
            "channelId": "channel_crypto",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        addresses = [{"address": "0x789GHI", "blockchains": ["base"]}]

        result = self.service.generate_onramp_url(
            addresses=addresses,
            preset_crypto_amount=0.5,
        )

        self.assertIn("presetCryptoAmount=0.5", result)

    @patch("purchase.services.coinbase_service.requests.post")
    @patch("purchase.services.coinbase_service.generate_jwt")
    def test_generate_onramp_url_no_token_in_response(
        self, mock_generate_jwt, mock_post
    ):
        """Test error handling when token is missing from response."""
        mock_generate_jwt.return_value = "test_jwt_token"

        # Mock response without token
        mock_response = Mock()
        mock_response.json.return_value = {"channelId": "channel_no_token"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        addresses = [{"address": "0x123", "blockchains": ["base"]}]

        with self.assertRaises(ValueError) as context:
            self.service.generate_onramp_url(addresses=addresses)

        self.assertIn(
            "Failed to get session token from response", str(context.exception)
        )

    @override_settings(COINBASE_API_KEY_ID=None, COINBASE_API_KEY_SECRET=None)
    def test_generate_onramp_url_without_credentials(self):
        """Test onramp URL generation without API credentials."""
        service = CoinbaseService()

        with self.assertRaises(ValueError) as context:
            service.generate_onramp_url(
                addresses=[{"address": "0x123", "blockchains": ["base"]}]
            )

        self.assertIn("Coinbase API credentials not configured", str(context.exception))
