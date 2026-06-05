import uuid
from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from user.tests.helpers import create_user

TEST_IP = "8.8.8.8"


class TestCoinbaseViewSet(TestCase):
    """Test cases for CoinbaseViewSet."""

    def setUp(self):
        """Set up test environment."""
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(user=self.user)
        self.url = "/api/payment/coinbase/create-onramp/"

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_generate_onramp_url_success(self, MockCoinbaseService):
        """Test successful onramp URL generation."""
        # Mock the service
        mock_service = Mock()
        mock_service.generate_onramp_url.return_value = (
            "https://pay.coinbase.com/buy/select-asset?sessionToken=test_token"
        )
        MockCoinbaseService.return_value = mock_service

        request_data = {
            "assets": ["ETH", "USDC"],
            "default_network": "base",
            "preset_fiat_amount": 100,
            "default_asset": "ETH",
        }

        response = self.client.post(
            self.url,
            data=request_data,
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("onramp_url", response.data)
        self.assertIn("expires_in_seconds", response.data)
        self.assertEqual(response.data["expires_in_seconds"], 300)

        # Verify service was called with user instead of addresses
        mock_service.generate_onramp_url.assert_called_once_with(
            user=self.user,
            assets=request_data["assets"],
            default_network=request_data["default_network"],
            preset_fiat_amount=request_data["preset_fiat_amount"],
            preset_crypto_amount=None,
            default_asset=request_data["default_asset"],
            client_ip=TEST_IP,
        )

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_generate_onramp_url_minimal(self, MockCoinbaseService):
        """Test onramp URL generation with minimal required data."""
        mock_service = Mock()
        mock_service.generate_onramp_url.return_value = (
            "https://pay.coinbase.com/buy/select-asset?sessionToken=test_token"
        )
        MockCoinbaseService.return_value = mock_service

        request_data = {}

        response = self.client.post(
            self.url,
            data=request_data,
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("onramp_url", response.data)

        # Verify optional parameters were passed as None
        mock_service.generate_onramp_url.assert_called_once_with(
            user=self.user,
            assets=None,
            default_network=None,
            preset_fiat_amount=None,
            preset_crypto_amount=None,
            default_asset=None,
            client_ip=TEST_IP,
        )

    def test_generate_onramp_url_unauthenticated(self):
        """Test that unauthenticated requests are rejected."""
        self.client.force_authenticate(user=None)

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_generate_onramp_url_service_error(self, MockCoinbaseService):
        """Test handling of service errors."""
        mock_service = Mock()
        mock_service.generate_onramp_url.side_effect = ValueError(
            "Coinbase API credentials not configured"
        )
        MockCoinbaseService.return_value = mock_service

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertEqual(
            response.data["error"], "Coinbase API credentials not configured"
        )

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_generate_onramp_url_unexpected_error(self, MockCoinbaseService):
        """Test handling of unexpected errors."""
        mock_service = Mock()
        mock_service.generate_onramp_url.side_effect = Exception("Unexpected error")
        MockCoinbaseService.return_value = mock_service

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"], "Failed to generate onramp URL")


class TestCoinbaseSessionTokenView(TestCase):
    """Test cases for the create-session-token endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(user=self.user)
        self.url = "/api/payment/coinbase/create-session-token/"

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_create_session_token_success(self, MockCoinbaseService):
        """Test successful session token creation with assets."""
        mock_service = Mock()
        mock_token = uuid.uuid4().hex
        mock_service.create_session_token.return_value = {
            "token": mock_token,
            "channel_id": "channel_123",
        }
        MockCoinbaseService.return_value = mock_service

        response = self.client.post(
            self.url,
            data={"assets": ["ETH", "USDC"]},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["token"], mock_token)
        self.assertEqual(response.data["channel_id"], "channel_123")
        self.assertEqual(response.data["expires_in_seconds"], 300)

        mock_service.create_session_token.assert_called_once_with(
            user=self.user,
            assets=["ETH", "USDC"],
            client_ip=TEST_IP,
        )

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_create_session_token_minimal(self, MockCoinbaseService):
        """Test session token creation with no optional params."""
        mock_service = Mock()
        mock_service.create_session_token.return_value = {
            "token": "tok_123",
            "channel_id": "ch_456",
        }
        MockCoinbaseService.return_value = mock_service

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

        mock_service.create_session_token.assert_called_once_with(
            user=self.user,
            assets=None,
            client_ip=TEST_IP,
        )

    def test_create_session_token_unauthenticated(self):
        """Test that unauthenticated requests are rejected."""
        self.client.force_authenticate(user=None)

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_create_session_token_value_error(self, MockCoinbaseService):
        """Test handling of ValueError from service."""
        mock_service = Mock()
        mock_service.create_session_token.side_effect = ValueError(
            "Coinbase API credentials not configured"
        )
        MockCoinbaseService.return_value = mock_service

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["error"], "Coinbase API credentials not configured"
        )

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_create_session_token_unexpected_error(self, MockCoinbaseService):
        """Test handling of unexpected errors."""
        mock_service = Mock()
        mock_service.create_session_token.side_effect = Exception("Unexpected error")
        MockCoinbaseService.return_value = mock_service

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["error"], "Failed to create session token")

    @patch("purchase.views.coinbase_view.get_client_ip")
    def test_create_session_token_no_client_ip(self, mock_get_ip):
        """Test that missing client IP returns 400."""
        mock_get_ip.return_value = None

        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unable to determine client IP", response.data["error"])

    def test_create_session_token_unauthorized_origin(self):
        """Test that unauthorized origins are rejected."""
        response = self.client.post(
            self.url,
            data={},
            format="json",
            HTTP_ORIGIN="https://malicious-site.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
