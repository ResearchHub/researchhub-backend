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
            "addresses": [
                {"address": "0x123456789", "blockchains": ["base", "ethereum"]}
            ],
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

        # Verify service was called with correct parameters
        mock_service.generate_onramp_url.assert_called_once_with(
            addresses=request_data["addresses"],
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

        request_data = {
            "addresses": [{"address": "0x987654321", "blockchains": ["base"]}]
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

        # Verify optional parameters were passed as None
        mock_service.generate_onramp_url.assert_called_once_with(
            addresses=request_data["addresses"],
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

        request_data = {
            "addresses": [{"address": "0x123456789", "blockchains": ["base"]}]
        }

        response = self.client.post(
            self.url,
            data=request_data,
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_generate_onramp_url_invalid_data(self):
        """Test validation errors for invalid request data."""
        # Missing required field
        request_data = {}

        response = self.client.post(
            self.url,
            data=request_data,
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("addresses", response.data)

    def test_generate_onramp_url_empty_addresses(self):
        """Test validation error for empty addresses list."""
        request_data = {"addresses": []}

        response = self.client.post(
            self.url,
            data=request_data,
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("purchase.views.coinbase_view.CoinbaseService")
    def test_generate_onramp_url_service_error(self, MockCoinbaseService):
        """Test handling of service errors."""
        mock_service = Mock()
        mock_service.generate_onramp_url.side_effect = ValueError(
            "Coinbase API credentials not configured"
        )
        MockCoinbaseService.return_value = mock_service

        request_data = {
            "addresses": [{"address": "0x123456789", "blockchains": ["base"]}]
        }

        response = self.client.post(
            self.url,
            data=request_data,
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

        request_data = {
            "addresses": [{"address": "0x123456789", "blockchains": ["base"]}]
        }

        response = self.client.post(
            self.url,
            data=request_data,
            format="json",
            HTTP_ORIGIN="https://www.researchhub.com",
            HTTP_X_FORWARDED_FOR=TEST_IP,
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"], "Failed to generate onramp URL")
