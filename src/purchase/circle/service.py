import logging
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.db import transaction

from purchase.circle.client import (
    CircleTransferResult,
    CircleWalletClient,
    CircleWalletFrozenError,
)
from purchase.models import Wallet
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Deposit
from user.models import User

logger = logging.getLogger(__name__)

# Circle terminal states used across webhook handling and sweep tracking.
COMPLETED_STATES = {"COMPLETED", "COMPLETE"}
FAILED_STATES = {"FAILED", "CANCELLED", "DENIED"}

# Circle inbound transaction states that indicate the deposit is in progress
# but not yet finalized (i.e. not yet safe to credit the user).
PENDING_DEPOSIT_STATES = {"INITIATED", "CONFIRMED"}

# Single source of truth for network <-> Circle blockchain mappings.
_NETWORK_DEFS = [
    {
        "network": "ETHEREUM",
        "mainnet_blockchain": "ETH",
        "testnet_blockchain": "ETH-SEPOLIA",
    },
    {
        "network": "BASE",
        "mainnet_blockchain": "BASE",
        "testnet_blockchain": "BASE-SEPOLIA",
    },
]

# Map Circle blockchain identifiers to our Deposit.network choices (both envs).
BLOCKCHAIN_TO_NETWORK = {
    d["mainnet_blockchain"]: d["network"] for d in _NETWORK_DEFS
} | {d["testnet_blockchain"]: d["network"] for d in _NETWORK_DEFS}


def process_circle_deposit(
    circle_transaction_id: str,
    wallet: Wallet,
    amount: str,
    network: str,
    from_address: str = "",
    transaction_hash: str = "",
) -> tuple[Deposit, bool]:
    """
    Idempotently record a Circle deposit, credit the user, and dispatch a sweep.

    If a pending Deposit already exists (created by an earlier INITIATED or
    CONFIRMED webhook), it is promoted to PAID. If no Deposit exists, one is
    created and immediately marked PAID.

    If the Deposit is already PAID, the user is *not* credited again and no
    sweep is dispatched.

    Args:
        circle_transaction_id: Circle's unique transaction identifier.
        wallet: The user's ``Wallet`` instance (must have ``user`` loaded).
        amount: Deposit amount as a decimal string.
        network: ``"ETHEREUM"`` or ``"BASE"``.
        from_address: On-chain source address.
        transaction_hash: On-chain tx hash.

    Returns:
        A ``(deposit, credited)`` tuple where *credited* is True if the user's
        balance was credited during this call.
    """
    user = wallet.user
    credited = False

    with transaction.atomic():
        deposit, created = Deposit.objects.get_or_create(
            circle_transaction_id=circle_transaction_id,
            defaults={
                "user": user,
                "amount": amount,
                "network": network,
                "from_address": from_address,
                "transaction_hash": transaction_hash,
                "sweep_status": Deposit.SWEEP_PENDING,
                "circle_status": Deposit.CIRCLE_COMPLETED,
            },
        )

        if created:
            # Brand-new deposit (no prior INITIATED/CONFIRMED webhook).
            deposit.set_paid()
            credited = True
        elif deposit.paid_status != Deposit.PAID:
            # Existing pending deposit from an earlier webhook — promote it.
            deposit.circle_status = Deposit.CIRCLE_COMPLETED
            deposit.sweep_status = Deposit.SWEEP_PENDING
            deposit.set_paid()  # sets paid_status=PAID, paid_date=now(), saves
            credited = True

        if credited:
            distribution = Dist("DEPOSIT", amount, give_rep=False)
            distributor = Distributor(distribution, user, deposit, time.time(), user)
            distributor.distribute()

    if credited:
        user.ensure_staking_opted_in()
        logger.info(
            "Circle deposit credited: user=%s amount=%s network=%s "
            "circle_transaction_id=%s",
            user.id,
            amount,
            network,
            circle_transaction_id,
        )
    else:
        logger.info(
            "Duplicate Circle transaction %s, skipping credit",
            circle_transaction_id,
        )

    return deposit, credited


# Sweeps worth this amount or more (in USD) go to the multisig;
# smaller sweeps go to the hot wallet.
SWEEP_MULTISIG_THRESHOLD_USD = 10_000

# Map Deposit.network values to Circle blockchain identifiers (derived from _NETWORK_DEFS).
NETWORK_TO_BLOCKCHAIN_MAINNET = {
    d["network"]: d["mainnet_blockchain"] for d in _NETWORK_DEFS
}
NETWORK_TO_BLOCKCHAIN_TESTNET = {
    d["network"]: d["testnet_blockchain"] for d in _NETWORK_DEFS
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


class CircleZeroBalanceError(Exception):
    """Raised when a sweep is attempted on a wallet with zero balance."""

    pass


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
        """Create new Circle wallets (ETH + Base) and store both wallet IDs."""
        idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"rh-wallet-{wallet.pk}"))
        full_name = user.get_full_name().strip()
        wallet_name = f"{full_name}'s wallet" if full_name else None
        result = self.client.create_wallet(
            idempotency_key=idempotency_key,
            wallet_name=wallet_name,
            ref_id=str(user.id),
        )

        wallet.circle_wallet_id = result.eth_wallet_id
        wallet.circle_base_wallet_id = result.base_wallet_id
        wallet.wallet_type = Wallet.WALLET_TYPE_CIRCLE
        wallet.save(
            update_fields=["circle_wallet_id", "circle_base_wallet_id", "wallet_type"]
        )

        logger.info(
            "Circle wallets created for wallet pk=%s, "
            "eth_wallet_id=%s, base_wallet_id=%s",
            wallet.pk,
            result.eth_wallet_id,
            result.base_wallet_id,
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

    def _get_sweep_destination(self, amount: str) -> str:
        """
        Return the destination address for a sweep based on USD value.

        Amounts worth >= SWEEP_MULTISIG_THRESHOLD_USD go to the multisig;
        smaller amounts go to the hot wallet.
        """

        multisig = getattr(settings, "RH_MULTISIG_ADDRESS", None)
        hot_wallet = getattr(settings, "WEB3_WALLET_ADDRESS", None)

        usd_value = RscExchangeRate.rsc_to_usd(float(amount))

        if usd_value >= SWEEP_MULTISIG_THRESHOLD_USD:
            if not multisig:
                raise ValueError("RH_MULTISIG_ADDRESS is not configured")
            return multisig
        else:
            if not hot_wallet:
                raise ValueError("WEB3_WALLET_ADDRESS is not configured")
            return hot_wallet

    def sweep_wallet(
        self,
        circle_wallet_id: str,
        amount: str,
        network: str,
        sweep_reference: str,
    ) -> CircleTransferResult:
        """
        Sweep the full RSC balance from a user's Circle wallet.

        Reads the wallet's actual token balance and sweeps the entire amount.
        Amounts worth >= $10,000 USD are sent to the multisig wallet;
        smaller amounts are sent to the hot wallet.

        Args:
            circle_wallet_id: The Circle wallet UUID to sweep from.
            amount: Original deposit amount (used for logging comparison only).
            network: Deposit network ("ETHEREUM" or "BASE").
            sweep_reference: Unique per-deposit reference used for idempotency
                (for example, Circle notification ID).

        Returns:
            CircleTransferResult with transfer_id and state.

        Raises:
            ValueError: If the network is unsupported or destination wallet
                is not configured.
            CircleZeroBalanceError: If the wallet has zero balance.
            CircleBalanceError: If the balance fetch fails.
            CircleTransferError: If the Circle API call fails.
        """
        blockchain = get_network_to_blockchain().get(network)
        if not blockchain:
            raise ValueError(f"Unsupported network for sweep: {network}")

        rsc_address_fn = NETWORK_TO_RSC_ADDRESS.get(network)
        if not rsc_address_fn:
            raise ValueError(f"No RSC token address configured for network: {network}")
        rsc_address = rsc_address_fn()

        # Fetch actual wallet balance instead of using the deposit amount.
        wallet_balance = self.client.get_wallet_balance(
            wallet_id=circle_wallet_id,
            token_address=rsc_address,
        )

        logger.info(
            "sweep_balance_fetched: circle_wallet_id=%s wallet_balance=%s "
            "original_deposit_amount=%s network=%s sweep_reference=%s",
            circle_wallet_id,
            wallet_balance,
            amount,
            network,
            sweep_reference,
        )

        if wallet_balance == Decimal(0):
            logger.error(
                "sweep_zero_balance: circle_wallet_id=%s "
                "original_deposit_amount=%s network=%s sweep_reference=%s",
                circle_wallet_id,
                amount,
                network,
                sweep_reference,
            )
            raise CircleZeroBalanceError(
                f"Wallet {circle_wallet_id} has zero RSC balance "
                f"(expected ~{amount}). sweep_reference={sweep_reference}"
            )

        sweep_amount = str(wallet_balance)
        destination = self._get_sweep_destination(sweep_amount)

        idempotency_key = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"rh-sweep-{sweep_reference}")
        )

        result = self.client.create_transfer(
            wallet_id=circle_wallet_id,
            destination_address=destination,
            token_address=rsc_address,
            blockchain=blockchain,
            amount=sweep_amount,
            idempotency_key=idempotency_key,
        )

        logger.info(
            "Sweep initiated: circle_wallet_id=%s sweep_amount=%s "
            "original_deposit_amount=%s network=%s "
            "destination=%s sweep_reference=%s transfer_id=%s state=%s",
            circle_wallet_id,
            sweep_amount,
            amount,
            network,
            destination,
            sweep_reference,
            result.transfer_id,
            result.state,
        )

        return result

    def execute_sweep(
        self,
        circle_wallet_id: str,
        amount: str,
        network: str,
        sweep_reference: str,
    ) -> None:
        """
        Execute a sweep and update the Deposit record accordingly.

        This contains the business logic previously in the Celery task:
        calls sweep_wallet, then updates Deposit.sweep_status based on
        the outcome.

        Args:
            circle_wallet_id: The Circle wallet UUID to sweep from.
            amount: Original deposit amount.
            network: "ETHEREUM" or "BASE".
            sweep_reference: Unique reference (Circle transaction ID).

        Raises:
            Exception: Any retryable error — sweep_status unchanged (caller should retry).
                Non-retryable errors (ValueError, CircleZeroBalanceError) are
                handled internally and do not propagate.
        """
        deposit = Deposit.objects.filter(circle_transaction_id=sweep_reference).first()

        sweep_status = None
        transfer_id = None

        try:
            result = self.sweep_wallet(
                circle_wallet_id=circle_wallet_id,
                amount=amount,
                network=network,
                sweep_reference=sweep_reference,
            )
            if result.state in COMPLETED_STATES:
                sweep_status = Deposit.SWEEP_COMPLETED
            else:
                sweep_status = Deposit.SWEEP_INITIATED
            transfer_id = result.transfer_id
        except CircleZeroBalanceError:
            logger.info(
                "Sweep wallet has zero balance (already swept): "
                "circle_wallet_id=%s sweep_reference=%s",
                circle_wallet_id,
                sweep_reference,
            )
            sweep_status = Deposit.SWEEP_COMPLETED
        except ValueError:
            logger.exception(
                "Sweep failed (not retryable): circle_wallet_id=%s amount=%s "
                "network=%s sweep_reference=%s",
                circle_wallet_id,
                amount,
                network,
                sweep_reference,
            )
            sweep_status = Deposit.SWEEP_FAILED
        except Exception:
            logger.exception(
                "Sweep failed (retrying): circle_wallet_id=%s amount=%s "
                "network=%s sweep_reference=%s",
                circle_wallet_id,
                amount,
                network,
                sweep_reference,
            )
            raise
        finally:
            if deposit and sweep_status:
                deposit.sweep_status = sweep_status
                update_fields = ["sweep_status"]
                if transfer_id:
                    deposit.sweep_transfer_id = transfer_id
                    update_fields.append("sweep_transfer_id")
                deposit.save(update_fields=update_fields)
