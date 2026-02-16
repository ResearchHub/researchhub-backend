from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from purchase.circle.client import (
    CircleWalletCreationError,
    CircleWalletNotReadyError,
    CircleWalletResult,
)
from purchase.circle.service import CircleWalletService
from purchase.models import Wallet

User = get_user_model()


class TestCircleWalletService(TestCase):
    """Tests for CircleWalletService."""

    def setUp(self):
        self.mock_client = Mock()
        self.service = CircleWalletService(client=self.mock_client)
        self.user = User.objects.create_user(username="testUser1")

    def test_returns_existing_address(self):
        """When eth_address and circle_wallet_id are set, return without calling Circle."""
        wallet = Wallet.objects.create(
            user=self.user,
            eth_address="0xExistingAddress",
            circle_wallet_id="existing-id",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
        )

        result = self.service.get_or_create_deposit_address(self.user)

        self.assertEqual(result.address, "0xExistingAddress")
        self.assertFalse(result.provisioning)
        self.mock_client.create_wallet.assert_not_called()
        self.mock_client.get_wallet.assert_not_called()

    def test_polls_when_wallet_id_exists_but_no_address(self):
        """When circle_wallet_id exists but no eth_address, poll Circle."""
        wallet = Wallet.objects.create(
            user=self.user,
            circle_wallet_id="pending-wallet-id",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
        )

        self.mock_client.get_wallet.return_value = CircleWalletResult(
            wallet_id="pending-wallet-id",
            address="0xNewAddress",
            state="LIVE",
        )

        result = self.service.get_or_create_deposit_address(self.user)

        self.assertEqual(result.address, "0xNewAddress")
        self.mock_client.create_wallet.assert_not_called()
        self.mock_client.get_wallet.assert_called_once_with("pending-wallet-id")

        wallet.refresh_from_db()
        self.assertEqual(wallet.eth_address, "0xNewAddress")

    def test_creates_wallet_record_and_circle_wallet_when_none_exists(self):
        """When user has no wallet record at all, create both DB and Circle wallet."""
        self.mock_client.create_wallet.return_value = "new-circle-wallet-id"
        self.mock_client.get_wallet.return_value = CircleWalletResult(
            wallet_id="new-circle-wallet-id",
            address="0xBrandNewAddress",
            state="LIVE",
        )

        result = self.service.get_or_create_deposit_address(self.user)

        self.assertEqual(result.address, "0xBrandNewAddress")

        wallet = Wallet.objects.get(user=self.user)
        self.mock_client.create_wallet.assert_called_once_with(
            idempotency_key=f"rh-wallet-{wallet.pk}"
        )
        self.assertEqual(wallet.circle_wallet_id, "new-circle-wallet-id")
        self.assertEqual(wallet.eth_address, "0xBrandNewAddress")
        self.assertEqual(wallet.wallet_type, Wallet.WALLET_TYPE_CIRCLE)

    def test_creates_circle_wallet_when_empty_wallet_exists(self):
        """When user has an empty wallet record, create Circle wallet."""
        wallet = Wallet.objects.create(user=self.user)

        self.mock_client.create_wallet.return_value = "new-id"
        self.mock_client.get_wallet.return_value = CircleWalletResult(
            wallet_id="new-id",
            address="0xAddr",
            state="LIVE",
        )

        result = self.service.get_or_create_deposit_address(self.user)

        self.assertEqual(result.address, "0xAddr")
        self.mock_client.create_wallet.assert_called_once_with(
            idempotency_key=f"rh-wallet-{wallet.pk}"
        )

        wallet.refresh_from_db()
        self.assertEqual(wallet.circle_wallet_id, "new-id")
        self.assertEqual(wallet.eth_address, "0xAddr")

    def test_raises_not_ready_when_wallet_not_live(self):
        """When wallet is created but not LIVE, raise error. Wallet ID is saved."""
        self.mock_client.create_wallet.return_value = "pending-wallet-id"
        self.mock_client.get_wallet.side_effect = CircleWalletNotReadyError(
            "Not LIVE yet"
        )

        with self.assertRaises(CircleWalletNotReadyError):
            self.service.get_or_create_deposit_address(self.user)

        # Wallet ID should be saved even though address is not
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.circle_wallet_id, "pending-wallet-id")
        self.assertIsNone(wallet.eth_address)

    def test_raises_creation_error_on_api_failure(self):
        """When Circle API fails, raise CircleWalletCreationError."""
        self.mock_client.create_wallet.side_effect = CircleWalletCreationError(
            "API error"
        )

        with self.assertRaises(CircleWalletCreationError):
            self.service.get_or_create_deposit_address(self.user)

    def test_polls_not_ready_raises_when_only_wallet_id_exists(self):
        """When wallet_id exists but polling says not LIVE, raise error."""
        wallet = Wallet.objects.create(
            user=self.user,
            circle_wallet_id="pending-id",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
        )

        self.mock_client.get_wallet.side_effect = CircleWalletNotReadyError(
            "Still pending"
        )

        with self.assertRaises(CircleWalletNotReadyError):
            self.service.get_or_create_deposit_address(self.user)

        wallet.refresh_from_db()
        self.assertIsNone(wallet.eth_address)
