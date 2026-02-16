from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from purchase.circle.client import CircleWalletCreationError, CircleWalletNotReadyError
from purchase.circle.service import DepositAddressResult
from purchase.views import DepositAddressView

User = get_user_model()


class TestDepositAddressView(TestCase):
    """Tests for the DepositAddressView."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.service_mock = Mock()
        self.user = User.objects.create_user(username="user1")

    def test_returns_existing_address(self):
        """Test 200 when address is already provisioned."""
        self.service_mock.get_or_create_deposit_address.return_value = (
            DepositAddressResult(address="0xABC123")
        )

        request = self.factory.get("/api/wallet/deposit-address/")
        force_authenticate(request, user=self.user)

        response = DepositAddressView.as_view()(request, service=self.service_mock)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["address"], "0xABC123")
        self.assertFalse(response.data["provisioning"])

    def test_returns_202_when_not_ready(self):
        """Test 202 when wallet is being provisioned."""
        self.service_mock.get_or_create_deposit_address.side_effect = (
            CircleWalletNotReadyError("Not LIVE")
        )

        request = self.factory.get("/api/wallet/deposit-address/")
        force_authenticate(request, user=self.user)

        response = DepositAddressView.as_view()(request, service=self.service_mock)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response["Retry-After"], "3")
        self.assertIn("retry", response.data["message"].lower())

    def test_returns_500_on_creation_error(self):
        """Test 500 when Circle API fails."""
        self.service_mock.get_or_create_deposit_address.side_effect = (
            CircleWalletCreationError("API down")
        )

        request = self.factory.get("/api/wallet/deposit-address/")
        force_authenticate(request, user=self.user)

        response = DepositAddressView.as_view()(request, service=self.service_mock)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_returns_500_on_unexpected_error(self):
        """Test 500 on unexpected exceptions."""
        self.service_mock.get_or_create_deposit_address.side_effect = RuntimeError(
            "Unexpected"
        )

        request = self.factory.get("/api/wallet/deposit-address/")
        force_authenticate(request, user=self.user)

        response = DepositAddressView.as_view()(request, service=self.service_mock)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_unauthenticated_returns_403(self):
        """Test that unauthenticated requests are rejected."""
        request = self.factory.get("/api/wallet/deposit-address/")

        response = DepositAddressView.as_view()(request)

        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
