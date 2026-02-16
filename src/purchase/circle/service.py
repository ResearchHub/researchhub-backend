import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from purchase.circle.client import CircleWalletClient, CircleWalletNotReadyError
from purchase.models import Wallet

logger = logging.getLogger(__name__)


@dataclass
class DepositAddressResult:
    """Result of requesting a user's deposit address."""

    address: str
    provisioning: bool = False


class CircleWalletService:
    """
    Service for lazy Circle wallet provisioning.

    When a user requests a deposit address, this service either returns their
    existing Circle wallet address or provisions a new one via the Circle API.
    """

    def __init__(self, client: Optional[CircleWalletClient] = None):
        self.client = client or CircleWalletClient()

    def get_or_create_deposit_address(self, user) -> DepositAddressResult:
        """
        Get (or provision) the Circle deposit address for a user.

        Flow:
        1. If the wallet already has an eth_address with a Circle wallet_type,
           return it immediately.
        2. If user has a circle_wallet_id but no eth_address (prior creation
           was initiated but wallet wasn't LIVE yet), poll Circle.
        3. If user has neither, create a new Circle wallet and poll.

        Args:
            user: The authenticated Django User instance.

        Returns:
            DepositAddressResult with the on-chain address.

        Raises:
            CircleWalletNotReadyError: If the wallet is created but not yet
                LIVE (caller should retry after a short delay).
            CircleWalletCreationError: If Circle API fails.
        """
        # Phase 1: Lock the wallet row and determine what action is needed.
        # If we need to create a Circle wallet, do it inside this transaction
        # so the wallet_id is persisted even if polling later fails.
        with transaction.atomic():
            wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)

            # Already fully provisioned
            if wallet.circle_wallet_id and wallet.eth_address:
                return DepositAddressResult(address=wallet.eth_address)

            # No Circle wallet yet — create one and persist the ID
            if not wallet.circle_wallet_id:
                self._create_wallet(wallet)

        # Phase 2: Poll for the address outside the transaction so that
        # a CircleWalletNotReadyError does NOT roll back the wallet_id save.
        return self._poll_and_store_address(wallet)

    def _create_wallet(self, wallet: Wallet) -> None:
        """Create a new Circle wallet and store the wallet ID."""
        idempotency_key = f"rh-wallet-{wallet.pk}"
        wallet_id = self.client.create_wallet(idempotency_key=idempotency_key)

        wallet.circle_wallet_id = wallet_id
        wallet.wallet_type = Wallet.WALLET_TYPE_CIRCLE
        wallet.save(update_fields=["circle_wallet_id", "wallet_type"])

        logger.info(
            "Circle wallet created for wallet pk=%s, circle_wallet_id=%s",
            wallet.pk,
            wallet_id,
        )

    def _poll_and_store_address(self, wallet: Wallet) -> DepositAddressResult:
        """Poll Circle for wallet state. Store eth_address if LIVE."""
        try:
            result = self.client.get_wallet(wallet.circle_wallet_id)
        except CircleWalletNotReadyError:
            logger.info(
                "Circle wallet %s not yet LIVE for wallet pk=%s",
                wallet.circle_wallet_id,
                wallet.pk,
            )
            raise

        wallet.eth_address = result.address
        wallet.save(update_fields=["eth_address"])

        logger.info(
            "Circle address stored for wallet pk=%s: %s",
            wallet.pk,
            result.address,
        )

        return DepositAddressResult(address=result.address)
