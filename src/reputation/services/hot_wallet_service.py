import hashlib
import logging

from django.db import connection, transaction
from django.db.models import Max
from web3 import Web3

from ethereum.lib import execute_erc20_transfer, get_network_config
from reputation.models import HotWalletNonceReservation, Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin

logger = logging.getLogger(__name__)


class WalletBusyError(Exception):
    """Another worker is reserving a nonce for this wallet."""


class UnsafeNonceError(Exception):
    """The node suggested a nonce that cannot safely be used."""


class HotWalletService:
    def __init__(self, transfer=None):
        self.transfer = transfer or execute_erc20_transfer

    def send(
        self,
        *,
        w3,
        network,
        sender,
        private_key,
        contract,
        to_address,
        amount,
        withdrawal_id=None,
        prepare=None,
    ):
        # A caller's outer transaction could undo the reservation after a send.
        if connection.in_atomic_block:
            raise RuntimeError("Hot-wallet sends require an outermost transaction")
        if private_key is None:
            raise ValueError("Hot-wallet signing key is unavailable")
        if amount <= 0:
            raise ValueError("Hot-wallet transfer amount must be positive")

        sender = Web3.to_checksum_address(sender)
        to_address = Web3.to_checksum_address(to_address)
        chain_id = get_network_config(network.lower())["chain_id"]
        if w3.eth.chain_id != chain_id:
            raise UnsafeNonceError(
                "Hot-wallet provider is connected to the wrong chain"
            )

        with transaction.atomic(durable=True):
            # PostgreSQL releases this lock on commit/crash. All hot-wallet
            # operations share it, including burns. Network sends happen only
            # after the reservation commits; uniqueness protects overlapping sends.
            lock_id = int.from_bytes(
                hashlib.sha256(
                    f"hot-wallet:{chain_id}:{sender.lower()}".encode()
                ).digest()[:8],
                signed=True,
            )
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [lock_id])
                if not cursor.fetchone()[0]:
                    raise WalletBusyError("Hot-wallet nonce reservation is busy")

            withdrawal = None
            if withdrawal_id is not None:
                withdrawal = Withdrawal.objects.select_for_update().get(
                    id=withdrawal_id
                )
                if (
                    withdrawal.transaction_hash
                    or withdrawal.broadcast_nonce is not None
                    or withdrawal.paid_status
                    not in (
                        PaidStatusModelMixin.INITIATED,
                        PaidStatusModelMixin.PENDING,
                    )
                    or HotWalletNonceReservation.objects.filter(
                        withdrawal=withdrawal
                    ).exists()
                ):
                    return withdrawal.transaction_hash
                # The locked record is authoritative; do not send stale task data.
                if (
                    withdrawal.network != network
                    or withdrawal.from_address.lower() != sender.lower()
                    or withdrawal.to_address.lower() != to_address.lower()
                    or str(withdrawal.amount) != str(amount)
                ):
                    raise ValueError("Withdrawal changed before nonce reservation")

            nonce = w3.eth.get_transaction_count(sender, "pending")
            confirmed = w3.eth.get_transaction_count(sender, "latest")
            reserved = HotWalletNonceReservation.objects.filter(
                chain_id=chain_id, sender__iexact=sender
            ).aggregate(last=Max("nonce"))["last"]
            # Include legacy/soft-deleted rows without rewriting historical
            # duplicates. A stale node must not reuse any recorded nonce.
            legacy = Withdrawal.all_objects.filter(
                network=network, from_address__iexact=sender
            ).aggregate(last=Max("broadcast_nonce"))["last"]
            floor = max(n for n in (reserved, legacy, -1) if n is not None)
            if nonce < confirmed or nonce <= floor:
                logger.error(
                    "Unsafe hot-wallet nonce: chain=%s sender=%s nonce=%s "
                    "confirmed=%s recorded=%s; submission stopped",
                    chain_id,
                    sender,
                    nonce,
                    confirmed,
                    floor,
                )
                raise UnsafeNonceError("RPC returned an already used or reserved nonce")

            # Burns commit their ledger debit with the reservation, so an
            # ambiguous network response cannot roll the debit back.
            if prepare is not None:
                prepare()
            reservation = HotWalletNonceReservation.objects.create(
                chain_id=chain_id,
                sender=sender.lower(),
                nonce=nonce,
                withdrawal=withdrawal,
                to_address=to_address,
                amount=str(amount),
            )
            if withdrawal is not None:
                withdrawal.broadcast_nonce = nonce
                withdrawal.paid_status = PaidStatusModelMixin.PENDING
                withdrawal.save(update_fields=["broadcast_nonce", "paid_status"])

        # From this point, all errors are treated as uncertain. Keep the
        # reservation and debit for manual review; never allocate a new nonce.
        try:
            tx_hash = self.transfer(
                w3,
                sender,
                private_key,
                contract,
                to_address,
                amount,
                network=network,
                nonce=nonce,
            )
            reservation.transaction_hash = tx_hash
            reservation.save(update_fields=["transaction_hash"])
            if withdrawal is not None:
                Withdrawal.objects.filter(id=withdrawal.id).update(
                    transaction_hash=tx_hash
                )
            return tx_hash
        except Exception as exc:
            logger.exception(
                "Hot-wallet submission uncertain; manual review required: "
                "reservation=%s withdrawal=%s chain=%s nonce=%s",
                reservation.id,
                withdrawal_id,
                chain_id,
                nonce,
            )
            HotWalletNonceReservation.objects.filter(id=reservation.id).update(
                error=str(exc)
            )
            raise
