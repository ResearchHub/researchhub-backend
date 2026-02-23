import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import transaction

from purchase.circle.client import (
    CircleTransferResult,
    CircleWalletClient,
    CircleWalletFrozenError,
)
from purchase.models import Wallet
from user.models import User

logger = logging.getLogger(__name__)

# Map Deposit.network values to Circle blockchain identifiers
NETWORK_TO_BLOCKCHAIN_MAINNET = {
    "ETHEREUM": "ETH",
    "BASE": "BASE",
}

NETWORK_TO_BLOCKCHAIN_TESTNET = {
    "ETHEREUM": "ETH-SEPOLIA",
    "BASE": "BASE-SEPOLIA",
}


def get_network_to_blockchain():
    if settings.PRODUCTION:
        return NETWORK_TO_BLOCKCHAIN_MAINNET
    return NETWORK_TO_BLOCKCHAIN_TESTNET


# Map network to the RSC token contract address on that chain
NETWORK_TO_RSC_ADDRESS = {
    "ETHEREUM": lambda: settings.WEB3_RSC_ADDRESS,
    "BASE": lambda: settings.WEB3_BASE_RSC_ADDRESS,
}


@dataclass
class DepositAddressResult:
    """Result of requesting a user's deposit address."""

    address: str


class CircleWalletService:
    """
    Service for lazy Circle wallet provisioning.

    When a user requests a deposit address, this service either returns their
    existing Circle wallet address or provisions a new one via the Circle API.
    """

    def __init__(self, client: Optional[CircleWalletClient] = None):
        self.client = client or CircleWalletClient()

    def get_or_create_deposit_address(self, user: User) -> DepositAddressResult:
        """
        Get (or provision) the Circle deposit address for a user.

        Flow:
        1. If the wallet already has an address with a Circle wallet_type,
           return it immediately.
        2. If user has a circle_wallet_id but no address, fetch from Circle.
        3. If user has neither, create a new Circle wallet and fetch.

        Args:
            user: The authenticated Django User instance.

        Returns:
            DepositAddressResult with the on-chain address.

        Raises:
            CircleWalletFrozenError: If the wallet is not in LIVE state.
            CircleWalletCreationError: If Circle API fails.
        """
        # Phase 1: Lock the wallet row and determine what action is needed.
        # If we need to create a Circle wallet, do it inside this transaction
        # so the wallet_id is persisted even if polling later fails.
        with transaction.atomic():
            wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)

            # Already fully provisioned
            if wallet.circle_wallet_id and wallet.address:
                return DepositAddressResult(address=wallet.address)

            # No Circle wallet yet — create one and persist the ID
            if not wallet.circle_wallet_id:
                self._create_wallet(wallet, user)

        # Phase 2: Fetch the address outside the transaction so that
        # a CircleWalletFrozenError does NOT roll back the wallet_id save.
        return self._fetch_and_store_address(wallet)

    def _create_wallet(self, wallet: Wallet, user: User) -> None:
        """Create a new Circle wallet and store the wallet ID."""
        idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"rh-wallet-{wallet.pk}"))
        full_name = user.get_full_name().strip()
        wallet_name = f"{full_name}'s wallet" if full_name else None
        wallet_id = self.client.create_wallet(
            idempotency_key=idempotency_key,
            wallet_name=wallet_name,
            ref_id=str(user.id),
        )

        wallet.circle_wallet_id = wallet_id
        wallet.wallet_type = Wallet.WALLET_TYPE_CIRCLE
        wallet.save(update_fields=["circle_wallet_id", "wallet_type"])

        logger.info(
            "Circle wallet created for wallet pk=%s, circle_wallet_id=%s",
            wallet.pk,
            wallet_id,
        )

    def _fetch_and_store_address(self, wallet: Wallet) -> DepositAddressResult:
        """Fetch wallet state from Circle. Store address if LIVE."""
        result = self.client.get_wallet(wallet.circle_wallet_id)

        if result.state != "LIVE":
            raise CircleWalletFrozenError(
                f"Wallet {wallet.circle_wallet_id} is in state "
                f"'{result.state}', expected LIVE"
            )

        wallet.address = result.address
        wallet.save(update_fields=["address"])

        logger.info(
            "Circle address stored for wallet pk=%s: %s",
            wallet.pk,
            result.address,
        )

        return DepositAddressResult(address=result.address)

    def sweep_wallet(
        self, circle_wallet_id: str, amount: str, network: str
    ) -> CircleTransferResult:
        """
        Sweep deposited RSC from a user's Circle wallet to the RH multisig.

        Args:
            circle_wallet_id: The Circle wallet UUID to sweep from.
            amount: Amount of RSC to sweep as a decimal string.
            network: Deposit network ("ETHEREUM" or "BASE").

        Returns:
            CircleTransferResult with transfer_id and state.

        Raises:
            ValueError: If the network is unsupported or multisig is not configured.
            CircleTransferError: If the Circle API call fails.
        """
        multisig = getattr(settings, "RH_MULTISIG_ADDRESS", None)
        if not multisig:
            raise ValueError("RH_MULTISIG_ADDRESS is not configured")

        blockchain = get_network_to_blockchain().get(network)
        if not blockchain:
            raise ValueError(f"Unsupported network for sweep: {network}")

        rsc_address_fn = NETWORK_TO_RSC_ADDRESS.get(network)
        if not rsc_address_fn:
            raise ValueError(f"No RSC token address configured for network: {network}")
        rsc_address = rsc_address_fn()

        idempotency_key = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL, f"rh-sweep-{circle_wallet_id}-{amount}-{network}"
            )
        )

        result = self.client.create_transfer(
            wallet_id=circle_wallet_id,
            destination_address=multisig,
            token_address=rsc_address,
            blockchain=blockchain,
            amount=amount,
            idempotency_key=idempotency_key,
        )

        logger.info(
            "Sweep initiated: circle_wallet_id=%s amount=%s network=%s "
            "transfer_id=%s state=%s",
            circle_wallet_id,
            amount,
            network,
            result.transfer_id,
            result.state,
        )

        return result
