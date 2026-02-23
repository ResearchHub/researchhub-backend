import logging
import uuid
from dataclasses import dataclass

from circle.web3 import utils as circle_utils
from circle.web3.developer_controlled_wallets.api import TransactionsApi, WalletsApi
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


class CircleWalletCreationError(Exception):
    """Raised when Circle fails to create a wallet."""

    pass


class CircleWalletFrozenError(Exception):
    """Raised when a Circle wallet is in FROZEN state."""

    pass


class CircleTransferError(Exception):
    """Raised when Circle fails to create a transfer."""

    pass


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

    def create_wallet(
        self,
        idempotency_key: str | None = None,
        wallet_name: str | None = None,
        ref_id: str | None = None,
    ) -> str:
        """
        Request creation of a new SCA wallet on ETH and BASE.

        Circle wallet creation may be asynchronous. This method returns the
        wallet ID; the caller should use `get_wallet()` to check if the
        wallet is LIVE and retrieve the on-chain address.

        Args:
            idempotency_key: Key to prevent duplicate wallet creation on
                retries. Auto-generated if not provided.
            wallet_name: Human-readable name stored on Circle's side.
            ref_id: Reference ID (e.g. user ID) to link the wallet on
                Circle's side.

        Returns:
            The Circle wallet ID (UUID string).

        Raises:
            CircleWalletCreationError: If the API returns no wallets.
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

        wallet = wallets[0].actual_instance
        return wallet.id

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
            CircleTransferError: If the API returns no transaction data.
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

        response = self.transactions_api.create_developer_transaction_transfer(request)

        tx = response.data
        if tx is None:
            raise CircleTransferError(
                "Circle API returned no transaction data in transfer response"
            )

        actual = tx.actual_instance if hasattr(tx, "actual_instance") else tx
        return CircleTransferResult(
            transfer_id=actual.id,
            state=(
                actual.state.value
                if hasattr(actual.state, "value")
                else str(actual.state)
            ),
        )
