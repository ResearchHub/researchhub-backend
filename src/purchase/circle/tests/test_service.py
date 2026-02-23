from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from purchase.circle.client import (
    CircleTransferError,
    CircleTransferResult,
    CircleWalletCreationError,
    CircleWalletFrozenError,
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
        """When address and circle_wallet_id are set, return without calling Circle."""
        wallet = Wallet.objects.create(
            user=self.user,
            address="0xExistingAddress",
            circle_wallet_id="existing-id",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
        )

        result = self.service.get_or_create_deposit_address(self.user)

        self.assertEqual(result.address, "0xExistingAddress")
        self.mock_client.create_wallet.assert_not_called()
        self.mock_client.get_wallet.assert_not_called()

    def test_polls_when_wallet_id_exists_but_no_address(self):
        """When circle_wallet_id exists but no address, poll Circle."""
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
        self.assertEqual(wallet.address, "0xNewAddress")

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
            idempotency_key=f"rh-wallet-{wallet.pk}",
            wallet_name=None,
            ref_id=str(self.user.id),
        )
        self.assertEqual(wallet.circle_wallet_id, "new-circle-wallet-id")
        self.assertEqual(wallet.address, "0xBrandNewAddress")
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
            idempotency_key=f"rh-wallet-{wallet.pk}",
            wallet_name=None,
            ref_id=str(self.user.id),
        )

        wallet.refresh_from_db()
        self.assertEqual(wallet.circle_wallet_id, "new-id")
        self.assertEqual(wallet.address, "0xAddr")

    def test_creates_wallet_with_user_name_in_metadata(self):
        """When user has a full name, pass it as wallet_name to Circle."""
        self.user.first_name = "John"
        self.user.last_name = "Doe"
        self.user.save(update_fields=["first_name", "last_name"])

        self.mock_client.create_wallet.return_value = "named-wallet-id"
        self.mock_client.get_wallet.return_value = CircleWalletResult(
            wallet_id="named-wallet-id",
            address="0xNamedAddr",
            state="LIVE",
        )

        self.service.get_or_create_deposit_address(self.user)

        wallet = Wallet.objects.get(user=self.user)
        self.mock_client.create_wallet.assert_called_once_with(
            idempotency_key=f"rh-wallet-{wallet.pk}",
            wallet_name="John Doe's wallet",
            ref_id=str(self.user.id),
        )

    def test_raises_not_live_when_wallet_frozen(self):
        """When wallet is FROZEN, raise error. Wallet ID is saved."""
        self.mock_client.create_wallet.return_value = "frozen-wallet-id"
        self.mock_client.get_wallet.return_value = CircleWalletResult(
            wallet_id="frozen-wallet-id",
            address="",
            state="FROZEN",
        )

        with self.assertRaises(CircleWalletFrozenError):
            self.service.get_or_create_deposit_address(self.user)

        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.circle_wallet_id, "frozen-wallet-id")
        self.assertIsNone(wallet.address)

    def test_raises_creation_error_on_api_failure(self):
        """When Circle API fails, raise CircleWalletCreationError."""
        self.mock_client.create_wallet.side_effect = CircleWalletCreationError(
            "API error"
        )

        with self.assertRaises(CircleWalletCreationError):
            self.service.get_or_create_deposit_address(self.user)

    def test_raises_not_live_when_existing_wallet_frozen(self):
        """When wallet_id exists but wallet is FROZEN, raise error."""
        wallet = Wallet.objects.create(
            user=self.user,
            circle_wallet_id="frozen-id",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
        )

        self.mock_client.get_wallet.return_value = CircleWalletResult(
            wallet_id="frozen-id",
            address="",
            state="FROZEN",
        )

        with self.assertRaises(CircleWalletFrozenError):
            self.service.get_or_create_deposit_address(self.user)

        wallet.refresh_from_db()
        self.assertIsNone(wallet.address)


@override_settings(
    RH_MULTISIG_ADDRESS="0xMultisigAddress",
    WEB3_RSC_ADDRESS="0xRSC_ETH",
    WEB3_BASE_RSC_ADDRESS="0xRSC_BASE",
)
class TestCircleWalletServiceSweep(TestCase):
    """Tests for CircleWalletService.sweep_wallet."""

    def setUp(self):
        self.mock_client = Mock()
        self.service = CircleWalletService(client=self.mock_client)

    def test_sweep_on_base(self):
        """Sweep calls create_transfer with correct BASE params."""
        self.mock_client.create_transfer.return_value = CircleTransferResult(
            transfer_id="tx-1", state="INITIATED"
        )

        result = self.service.sweep_wallet("circle-wallet-1", "100.0", "BASE")

        self.assertEqual(result.transfer_id, "tx-1")
        self.assertEqual(result.state, "INITIATED")
        self.mock_client.create_transfer.assert_called_once_with(
            wallet_id="circle-wallet-1",
            destination_address="0xMultisigAddress",
            token_address="0xRSC_BASE",
            blockchain="BASE",
            amount="100.0",
            idempotency_key="rh-sweep-circle-wallet-1-100.0-BASE",
        )

    def test_sweep_on_ethereum(self):
        """Sweep calls create_transfer with correct ETH params."""
        self.mock_client.create_transfer.return_value = CircleTransferResult(
            transfer_id="tx-2", state="INITIATED"
        )

        result = self.service.sweep_wallet("circle-wallet-2", "50.5", "ETHEREUM")

        self.assertEqual(result.transfer_id, "tx-2")
        self.mock_client.create_transfer.assert_called_once_with(
            wallet_id="circle-wallet-2",
            destination_address="0xMultisigAddress",
            token_address="0xRSC_ETH",
            blockchain="ETH",
            amount="50.5",
            idempotency_key="rh-sweep-circle-wallet-2-50.5-ETHEREUM",
        )

    def test_sweep_raises_when_no_multisig(self):
        """Raise ValueError when RH_MULTISIG_ADDRESS is empty."""
        with self.settings(RH_MULTISIG_ADDRESS=""):
            with self.assertRaises(ValueError) as ctx:
                self.service.sweep_wallet("wallet-1", "10", "BASE")
            self.assertIn("RH_MULTISIG_ADDRESS", str(ctx.exception))

    def test_sweep_raises_for_unsupported_network(self):
        """Raise ValueError for an unknown network."""
        with self.assertRaises(ValueError) as ctx:
            self.service.sweep_wallet("wallet-1", "10", "SOLANA")
        self.assertIn("Unsupported network", str(ctx.exception))

    def test_sweep_propagates_transfer_error(self):
        """CircleTransferError from client propagates."""
        self.mock_client.create_transfer.side_effect = CircleTransferError(
            "API failure"
        )

        with self.assertRaises(CircleTransferError):
            self.service.sweep_wallet("wallet-1", "10", "BASE")
