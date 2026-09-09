from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Event
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from reputation.models import HotWalletNonceReservation, Withdrawal
from reputation.services.hot_wallet_service import (
    HotWalletService,
    UnsafeNonceError,
    WalletBusyError,
)
from reputation.services.withdrawal_recovery_service import WithdrawalRecoveryService
from utils.test_helpers import AWSMockTransactionTestCase

SENDER = "0x7F57d306a9422ee8175aDc25898B1b2EBF1010cb"
RECIPIENT = "0x53357e6EAe3263c0a74732d0134E521d6DBEE837"


class HotWalletServiceTests(AWSMockTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.w3 = Mock()
        self.w3.eth.chain_id = 84532
        self.w3.eth.get_transaction_count.return_value = 3463
        self.transfer = Mock(return_value="0xsubmitted")
        self.service = HotWalletService(transfer=self.transfer)
        self.args = {
            "w3": self.w3,
            "network": "BASE",
            "sender": SENDER,
            "private_key": "mock-key",
            "contract": Mock(),
            "to_address": RECIPIENT,
            "amount": Decimal("2279.97"),
        }

    def withdrawal(self, **overrides):
        fields = {
            "from_address": SENDER,
            "to_address": RECIPIENT,
            "network": "BASE",
            "amount": "2279.97",
            "token_address": "0xtoken",
            "paid_status": "INITIATED",
            **overrides,
        }
        return Withdrawal.objects.create(**fields)

    def test_reservation_is_committed_before_network_send(self):
        # Arrange
        withdrawal = self.withdrawal()

        def send(*args, **kwargs):
            self.assertFalse(connections["default"].in_atomic_block)
            reservation = HotWalletNonceReservation.objects.get(withdrawal=withdrawal)
            self.assertEqual(reservation.nonce, 3463)
            withdrawal.refresh_from_db()
            self.assertEqual(withdrawal.paid_status, "PENDING")
            return "0xsubmitted"

        self.transfer.side_effect = send

        # Act
        self.service.send(**self.args, withdrawal_id=withdrawal.id)

        # Assert
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.transaction_hash, "0xsubmitted")
        self.assertEqual(withdrawal.broadcast_nonce, 3463)

    def test_stale_nonce_rejected_even_if_legacy_withdrawal_was_removed(self):
        # Arrange
        self.withdrawal(broadcast_nonce=3463, paid_status="PAID", is_removed=True)

        # Act / Assert
        with self.assertRaises(UnsafeNonceError):
            self.service.send(**self.args)
        self.transfer.assert_not_called()
        self.assertFalse(HotWalletNonceReservation.objects.exists())

    def test_nonce_below_confirmed_count_rejected(self):
        # Arrange
        self.w3.eth.get_transaction_count.side_effect = [3463, 3464]

        # Act / Assert
        with self.assertRaises(UnsafeNonceError):
            self.service.send(**self.args)
        self.transfer.assert_not_called()

    def test_wrong_chain_rejected_before_reservation(self):
        # Arrange
        self.w3.eth.chain_id = 1

        # Act / Assert
        with self.assertRaises(UnsafeNonceError):
            self.service.send(**self.args)
        self.transfer.assert_not_called()

    def test_withdrawal_and_burn_share_nonce_reservations(self):
        # Arrange
        withdrawal = self.withdrawal()
        self.service.send(**self.args, withdrawal_id=withdrawal.id)

        # Act / Assert
        with self.assertRaises(UnsafeNonceError):
            self.service.send(**self.args)  # Burn: no withdrawal record.
        self.transfer.assert_called_once()

    def test_database_rejects_duplicate_nonce_with_different_address_case(self):
        # Arrange
        self.service.send(**self.args)

        # Act / Assert
        with self.assertRaises(IntegrityError), transaction.atomic():
            HotWalletNonceReservation.objects.create(
                chain_id=84532,
                sender=SENDER,
                nonce=3463,
                to_address=RECIPIENT,
                amount="1",
            )

    def test_timeout_keeps_reservation_and_does_not_resubmit(self):
        # Arrange
        withdrawal = self.withdrawal()
        self.transfer.side_effect = TimeoutError("node response lost")

        # Act
        with self.assertRaises(TimeoutError):
            self.service.send(**self.args, withdrawal_id=withdrawal.id)
        self.service.send(**self.args, withdrawal_id=withdrawal.id)

        # Assert
        self.transfer.assert_called_once()
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.paid_status, "PENDING")
        self.assertEqual(withdrawal.nonce_reservation.error, "node response lost")

    def test_outer_transaction_is_rejected_before_sending(self):
        # Arrange / Act / Assert
        with transaction.atomic(), self.assertRaises(RuntimeError):
            self.service.send(**self.args)
        self.transfer.assert_not_called()

    def test_failed_preparation_does_not_reserve_or_send(self):
        # Arrange
        prepare = Mock(side_effect=ValueError("balance changed"))

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.send(**self.args, prepare=prepare)
        self.transfer.assert_not_called()
        self.assertFalse(HotWalletNonceReservation.objects.exists())

    def test_concurrent_withdrawal_and_burn_cannot_reserve_same_nonce(self):
        # Arrange
        reserved_lock = Event()
        release_worker = Event()
        withdrawal = self.withdrawal()
        worker_w3 = Mock()
        worker_w3.eth.chain_id = 84532

        def count(*args):
            reserved_lock.set()
            if not release_worker.wait(timeout=10):
                raise TimeoutError("test worker was not released")
            return 3463

        worker_w3.eth.get_transaction_count.side_effect = count

        def worker():
            try:
                return self.service.send(
                    **{**self.args, "w3": worker_w3}, withdrawal_id=withdrawal.id
                )
            finally:
                connections.close_all()

        # Act
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(worker)
            try:
                self.assertTrue(reserved_lock.wait(timeout=10))
                with self.assertRaises(WalletBusyError):
                    self.service.send(**self.args)
            finally:
                release_worker.set()
            self.assertEqual(result.result(timeout=10), "0xsubmitted")

        # Assert
        self.assertEqual(HotWalletNonceReservation.objects.count(), 1)
        self.transfer.assert_called_once()


class WithdrawalRecoveryServiceTests(AWSMockTransactionTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.evaluate = Mock(return_value=("PENDING", None))
        self.enqueue = Mock()
        self.service = WithdrawalRecoveryService(
            evaluate_receipt=self.evaluate, enqueue_broadcast=self.enqueue
        )
        self.withdrawal = Withdrawal.objects.create(
            from_address=SENDER,
            to_address=RECIPIENT,
            network="BASE",
            token_address="0xtoken",
            amount="100",
            paid_status="PENDING",
            transaction_hash="0xmissing",
            broadcast_nonce=3463,
        )

    def test_uncertain_broadcast_without_hash_is_not_requeued(self):
        # Arrange
        Withdrawal.objects.filter(id=self.withdrawal.id).update(transaction_hash=None)

        # Act
        self.service.check_pending()

        # Assert
        self.enqueue.assert_not_called()
        self.evaluate.assert_not_called()

    def test_pending_check_does_not_change_updated_date(self):
        # Arrange
        original = self.withdrawal.updated_date

        # Act
        self.service.check_pending()

        # Assert
        self.withdrawal.refresh_from_db()
        self.assertEqual(self.withdrawal.updated_date, original)

    def test_stale_alert_uses_creation_age_and_is_deduplicated(self):
        # Arrange
        Withdrawal.objects.filter(id=self.withdrawal.id).update(
            created_date=timezone.now() - timedelta(minutes=11),
            updated_date=timezone.now(),
        )

        # Act
        with patch("reputation.services.withdrawal_recovery_service.logger") as logger:
            self.service.check_pending()
            self.service.check_pending()

        # Assert
        logger.error.assert_called_once()

    def test_new_reservation_is_not_alerted_using_old_withdrawal_age(self):
        # Arrange
        Withdrawal.objects.filter(id=self.withdrawal.id).update(
            created_date=timezone.now() - timedelta(days=10)
        )
        HotWalletNonceReservation.objects.create(
            withdrawal=self.withdrawal,
            chain_id=84532,
            sender=SENDER,
            nonce=3463,
            to_address=RECIPIENT,
            amount="100",
        )

        # Act
        with patch("reputation.services.withdrawal_recovery_service.logger") as logger:
            self.service.check_pending()

        # Assert
        logger.error.assert_not_called()

    def test_manual_correction_after_listing_is_preserved(self):
        # Arrange
        select_for_update = Withdrawal.objects.select_for_update

        def correct_before_lock():
            Withdrawal.objects.filter(id=self.withdrawal.id).update(
                paid_status="FAILED"
            )
            return select_for_update()

        # Act
        with patch.object(
            Withdrawal.objects, "select_for_update", side_effect=correct_before_lock
        ):
            self.service.check_pending()

        # Assert
        self.withdrawal.refresh_from_db()
        self.assertEqual(self.withdrawal.paid_status, "FAILED")
        self.evaluate.assert_not_called()
