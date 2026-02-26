import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from circle.web3 import utils as circle_utils
from circle.web3.configurations.api.webhook_subscriptions_api import (
    WebhookSubscriptionsApi,
)
from circle.web3.developer_controlled_wallets.api import TransactionsApi, WalletsApi
from circle.web3.developer_controlled_wallets.exceptions import OpenApiException
from circle.web3.developer_controlled_wallets.models import (
    AccountType,
    Blockchain,
    CreateTransferTransactionForDeveloperRequest,
    CreateTransferTransactionForDeveloperRequestBlockchain,
    CreateWalletRequest,
    FeeLevel,
    TransferBlockchain,
    WalletMetadata,
)
from django.conf import settings

logger = logging.getLogger(__name__)

# Transfer states that indicate Circle accepted or finalized the transfer.
ACCEPTED_TRANSFER_STATES = {
    "INITIATED",
    "QUEUED",
    "SENT",
    "COMPLETE",
    "CONFIRMED",
    "CLEARED",
}


class CircleWalletCreationError(Exception):
    """Raised when Circle fails to create a wallet."""

    pass


class CircleWalletFrozenError(Exception):
    """Raised when a Circle wallet is in FROZEN state."""

    pass


class CircleTransferError(Exception):
    """Raised when Circle fails to create a transfer."""

    pass


class CircleBalanceError(Exception):
    """Raised when Circle fails to fetch a wallet balance."""

    pass


@dataclass
class CircleWalletCreationResult:
    """Result of creating Circle wallets (one per chain)."""

    eth_wallet_id: str
    base_wallet_id: str


@dataclass
class CircleWalletResult:
    """Result of fetching a Circle wallet."""

    wallet_id: str
    address: str
    state: str


@dataclass
class CircleTransferResult:
    """Result of initiating a Circle transfer."""

    transfer_id: str
    state: str


class CircleWalletClient:
    """
    Low-level client wrapping the Circle developer-controlled wallets SDK.

    Handles SDK initialization and provides methods for creating and
    fetching wallets.
    """

    def __init__(self):
        self._api_client = None
        self._wallets_api = None
        self._transactions_api = None
        self._webhook_subscriptions_api = None

    @property
    def api_client(self):
        if self._api_client is None:
            self._api_client = circle_utils.init_developer_controlled_wallets_client(
                api_key=settings.CIRCLE_API_KEY,
                entity_secret=settings.CIRCLE_ENTITY_SECRET,
            )
        return self._api_client

    @property
    def wallets_api(self):
        if self._wallets_api is None:
            self._wallets_api = WalletsApi(self.api_client)
        return self._wallets_api

    @property
    def transactions_api(self):
        if self._transactions_api is None:
            self._transactions_api = TransactionsApi(self.api_client)
        return self._transactions_api

    @property
    def webhook_subscriptions_api(self):
        if self._webhook_subscriptions_api is None:
            # Ensure the SDK is initialized (sets up circle_utils.CONF_CLIENT)
            self.api_client
            self._webhook_subscriptions_api = WebhookSubscriptionsApi(
                circle_utils.CONF_CLIENT
            )
        return self._webhook_subscriptions_api

    def get_notification_public_key(self, key_id: str) -> str:
        """Fetch a Circle notification public key by ID (base64-encoded DER)."""
        response = self.webhook_subscriptions_api.get_notification_signature(id=key_id)
        return response.data.public_key

    @staticmethod
    def _blockchain_family(blockchain_value: str) -> str | None:
        """Normalize a Circle blockchain identifier to 'ETH' or 'BASE'."""
        upper = (blockchain_value or "").upper()
        if upper.startswith("BASE"):
            return "BASE"
        if upper.startswith("ETH"):
            return "ETH"
        return None

    def create_wallet(
        self,
        idempotency_key: str | None = None,
        wallet_name: str | None = None,
        ref_id: str | None = None,
    ) -> CircleWalletCreationResult:
        """
        Request creation of a new SCA wallet on ETH and BASE.

        Circle creates one wallet per blockchain. Both wallets share the
        same on-chain address but have distinct wallet IDs.

        Args:
            idempotency_key: Key to prevent duplicate wallet creation on
                retries. Auto-generated if not provided.
            wallet_name: Human-readable name stored on Circle's side.
            ref_id: Reference ID (e.g. user ID) to link the wallet on
                Circle's side.

        Returns:
            CircleWalletCreationResult with wallet IDs for each chain.

        Raises:
            CircleWalletCreationError: If the API returns no wallets or
                a wallet for either chain is missing.
        """
        if not idempotency_key:
            idempotency_key = uuid.uuid4().hex

        metadata = None
        if wallet_name or ref_id:
            metadata = [WalletMetadata(name=wallet_name, refId=ref_id)]

        if settings.PRODUCTION:
            blockchains = [Blockchain.ETH, Blockchain.BASE]
        else:
            blockchains = [Blockchain.ETH_MINUS_SEPOLIA, Blockchain.BASE_MINUS_SEPOLIA]

        request = CreateWalletRequest(
            idempotencyKey=idempotency_key,
            blockchains=blockchains,
            walletSetId=settings.CIRCLE_WALLET_SET_ID,
            accountType=AccountType.SCA,
            count=1,
            metadata=metadata,
        )

        response = self.wallets_api.create_wallet(request)
        wallets = response.data.wallets

        if not wallets:
            raise CircleWalletCreationError(
                "Circle API returned no wallets in creation response"
            )

        # Map each wallet to its chain family (ETH or BASE).
        wallet_ids_by_chain: dict[str, str] = {}
        for wrapper in wallets:
            w = wrapper.actual_instance
            blockchain_str = (
                w.blockchain.value
                if hasattr(w.blockchain, "value")
                else str(w.blockchain)
            )
            family = self._blockchain_family(blockchain_str)
            if family:
                wallet_ids_by_chain[family] = w.id

        eth_id = wallet_ids_by_chain.get("ETH")
        base_id = wallet_ids_by_chain.get("BASE")

        if not eth_id or not base_id:
            raise CircleWalletCreationError(
                "Circle API did not return wallets for both chains. "
                f"Got: {wallet_ids_by_chain}"
            )

        return CircleWalletCreationResult(eth_wallet_id=eth_id, base_wallet_id=base_id)

    def get_wallet(self, wallet_id: str) -> CircleWalletResult:
        """
        Fetch the current state of a Circle wallet.

        Args:
            wallet_id: The Circle wallet UUID.

        Returns:
            CircleWalletResult with wallet details.
        """
        response = self.wallets_api.get_wallet(wallet_id)
        wallet = response.data.wallet.actual_instance

        return CircleWalletResult(
            wallet_id=wallet.id,
            address=wallet.address,
            state=wallet.state.value,
        )

    def get_wallet_balance(
        self,
        wallet_id: str,
        token_address: str,
    ) -> Decimal:
        """
        Fetch the balance of a specific token in a Circle wallet.

        Args:
            wallet_id: The Circle wallet UUID.
            token_address: Contract address of the token to look up.

        Returns:
            The token balance as a Decimal (zero if the token is not found).

        Raises:
            CircleBalanceError: If the API request fails.
        """
        try:
            response = self.wallets_api.list_wallet_balance(
                id=wallet_id,
                token_address=token_address,
            )
        except OpenApiException as exc:
            raise CircleBalanceError(
                f"Circle API error fetching balance for wallet {wallet_id}: {exc}"
            ) from exc
        except Exception as exc:
            raise CircleBalanceError(
                f"Unexpected error fetching balance for wallet {wallet_id}: {exc}"
            ) from exc

        for balance in response.data.token_balances or []:
            return Decimal(balance.amount)

        return Decimal(0)

    def create_transfer(
        self,
        wallet_id: str,
        destination_address: str,
        token_address: str,
        blockchain: str,
        amount: str,
        idempotency_key: str | None = None,
    ) -> CircleTransferResult:
        """
        Initiate an on-chain transfer from a developer-controlled wallet.

        Args:
            wallet_id: Source Circle wallet UUID.
            destination_address: On-chain destination address.
            token_address: Contract address of the token to transfer.
            blockchain: Target blockchain ("ETH" or "BASE").
            amount: Transfer amount as a decimal string.
            idempotency_key: Key to prevent duplicate transfers.

        Returns:
            CircleTransferResult with transfer ID and state.

        Raises:
            CircleTransferError: If the API request fails, returns no
                transaction data, or returns a terminal/unknown state.
        """
        if not idempotency_key:
            idempotency_key = uuid.uuid4().hex

        request = CreateTransferTransactionForDeveloperRequest(
            idempotency_key=idempotency_key,
            wallet_id=wallet_id,
            destination_address=destination_address,
            token_address=token_address,
            blockchain=CreateTransferTransactionForDeveloperRequestBlockchain(
                TransferBlockchain(blockchain)
            ),
            amounts=[amount],
            fee_level=FeeLevel.MEDIUM,
        )

        try:
            response = self.transactions_api.create_developer_transaction_transfer(
                request
            )
        except OpenApiException as exc:
            raise CircleTransferError(
                f"Circle API error creating transfer: {exc}"
            ) from exc
        except Exception as exc:
            raise CircleTransferError(
                f"Unexpected error creating Circle transfer: {exc}"
            ) from exc

        tx = response.data
        if tx is None:
            raise CircleTransferError(
                "Circle API returned no transaction data in transfer response"
            )

        actual = tx.actual_instance if hasattr(tx, "actual_instance") else tx
        state = (
            actual.state.value if hasattr(actual.state, "value") else str(actual.state)
        )
        if state not in ACCEPTED_TRANSFER_STATES:
            raise CircleTransferError(
                "Circle transfer returned terminal/unknown state "
                f"'{state}' for transfer_id={actual.id}"
            )

        return CircleTransferResult(
            transfer_id=actual.id,
            state=state,
        )
