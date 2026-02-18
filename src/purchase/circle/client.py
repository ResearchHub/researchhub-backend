import logging
import uuid
from dataclasses import dataclass

from circle.web3 import utils as circle_utils
from circle.web3.developer_controlled_wallets.api import WalletsApi
from circle.web3.developer_controlled_wallets.models import (
    AccountType,
    Blockchain,
    CreateWalletRequest,
)
from django.conf import settings

logger = logging.getLogger(__name__)


class CircleWalletCreationError(Exception):
    """Raised when Circle fails to create a wallet."""

    pass


class CircleWalletFrozenError(Exception):
    """Raised when a Circle wallet is in FROZEN state."""

    pass


@dataclass
class CircleWalletResult:
    """Result of fetching a Circle wallet."""

    wallet_id: str
    address: str
    state: str


class CircleWalletClient:
    """
    Low-level client wrapping the Circle developer-controlled wallets SDK.

    Handles SDK initialization and provides methods for creating and
    fetching wallets.
    """

    def __init__(self):
        self._wallets_api = None

    @property
    def wallets_api(self):
        if self._wallets_api is None:
            api_client = circle_utils.init_developer_controlled_wallets_client(
                api_key=settings.CIRCLE_API_KEY,
                entity_secret=settings.CIRCLE_ENTITY_SECRET,
            )
            self._wallets_api = WalletsApi(api_client)
        return self._wallets_api

    def create_wallet(self, idempotency_key: str | None = None) -> str:
        """
        Request creation of a new SCA wallet on ETH and BASE.

        Circle wallet creation may be asynchronous. This method returns the
        wallet ID; the caller should use `get_wallet()` to check if the
        wallet is LIVE and retrieve the on-chain address.

        Args:
            idempotency_key: Key to prevent duplicate wallet creation on
                retries. Auto-generated if not provided.

        Returns:
            The Circle wallet ID (UUID string).

        Raises:
            CircleWalletCreationError: If the API returns no wallets.
        """
        if not idempotency_key:
            idempotency_key = uuid.uuid4().hex

        request = CreateWalletRequest(
            idempotencyKey=idempotency_key,
            blockchains=[Blockchain.ETH, Blockchain.BASE],
            walletSetId=settings.CIRCLE_WALLET_SET_ID,
            accountType=AccountType.SCA,
            count=1,
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
