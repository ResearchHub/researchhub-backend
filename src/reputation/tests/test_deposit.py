from django.contrib.auth import get_user_model
from django.test import TestCase

from purchase.models import Wallet
from reputation.related_models.deposit import Deposit

User = get_user_model()


class DepositUpsertPendingTests(TestCase):
    """Direct unit tests for Deposit.upsert_pending status-ordering logic."""

    def setUp(self):
        self.user = User.objects.create_user(username="deposit_test_user")
        self.wallet = Wallet.objects.create(
            user=self.user,
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
        )

    def test_creates_new_deposit(self):
        deposit = Deposit.upsert_pending(
            circle_transaction_id="txn-001",
            wallet=self.wallet,
            amount="100.00",
            network="ETHEREUM",
            circle_status="INITIATED",
            from_address="0xabc",
            transaction_hash="0xhash",
        )

        self.assertEqual(deposit.user, self.user)
        self.assertEqual(deposit.amount, "100.00")
        self.assertEqual(deposit.network, "ETHEREUM")
        self.assertEqual(deposit.circle_status, "INITIATED")
        self.assertEqual(deposit.from_address, "0xabc")
        self.assertEqual(deposit.transaction_hash, "0xhash")
        self.assertEqual(deposit.paid_status, Deposit.PENDING)
        self.assertEqual(Deposit.objects.count(), 1)

    def test_status_advances_forward(self):
        """INITIATED → CONFIRMED should advance circle_status."""
        Deposit.upsert_pending(
            circle_transaction_id="txn-002",
            wallet=self.wallet,
            amount="50.00",
            network="BASE",
            circle_status="INITIATED",
        )

        deposit = Deposit.upsert_pending(
            circle_transaction_id="txn-002",
            wallet=self.wallet,
            amount="50.00",
            network="BASE",
            circle_status="CONFIRMED",
        )

        self.assertEqual(deposit.circle_status, "CONFIRMED")
        self.assertEqual(Deposit.objects.count(), 1)

    def test_status_does_not_regress(self):
        """CONFIRMED → INITIATED should NOT regress circle_status."""
        Deposit.upsert_pending(
            circle_transaction_id="txn-003",
            wallet=self.wallet,
            amount="75.00",
            network="ETHEREUM",
            circle_status="CONFIRMED",
        )

        deposit = Deposit.upsert_pending(
            circle_transaction_id="txn-003",
            wallet=self.wallet,
            amount="75.00",
            network="ETHEREUM",
            circle_status="INITIATED",
        )

        self.assertEqual(deposit.circle_status, "CONFIRMED")

    def test_completed_not_overridden_by_confirmed(self):
        """Once COMPLETED, the status should not go back to CONFIRMED."""
        Deposit.upsert_pending(
            circle_transaction_id="txn-004",
            wallet=self.wallet,
            amount="200.00",
            network="ETHEREUM",
            circle_status="COMPLETED",
        )

        deposit = Deposit.upsert_pending(
            circle_transaction_id="txn-004",
            wallet=self.wallet,
            amount="200.00",
            network="ETHEREUM",
            circle_status="CONFIRMED",
        )

        self.assertEqual(deposit.circle_status, "COMPLETED")

    def test_failed_not_overridden_by_confirmed(self):
        """Once FAILED, the status should not go back to CONFIRMED."""
        Deposit.upsert_pending(
            circle_transaction_id="txn-005",
            wallet=self.wallet,
            amount="200.00",
            network="ETHEREUM",
            circle_status="FAILED",
        )

        deposit = Deposit.upsert_pending(
            circle_transaction_id="txn-005",
            wallet=self.wallet,
            amount="200.00",
            network="ETHEREUM",
            circle_status="CONFIRMED",
        )

        self.assertEqual(deposit.circle_status, "FAILED")

    def test_failed_and_completed_at_same_level(self):
        """COMPLETED → FAILED should not advance (same order level)."""
        Deposit.upsert_pending(
            circle_transaction_id="txn-006",
            wallet=self.wallet,
            amount="300.00",
            network="ETHEREUM",
            circle_status="COMPLETED",
        )

        deposit = Deposit.upsert_pending(
            circle_transaction_id="txn-006",
            wallet=self.wallet,
            amount="300.00",
            network="ETHEREUM",
            circle_status="FAILED",
        )

        self.assertEqual(deposit.circle_status, "COMPLETED")

    def test_duplicate_transaction_id_no_new_row(self):
        """Multiple upserts with same transaction ID should not create new rows."""
        Deposit.upsert_pending(
            circle_transaction_id="txn-007",
            wallet=self.wallet,
            amount="100.00",
            network="ETHEREUM",
            circle_status="INITIATED",
        )
        Deposit.upsert_pending(
            circle_transaction_id="txn-007",
            wallet=self.wallet,
            amount="100.00",
            network="ETHEREUM",
            circle_status="CONFIRMED",
        )
        Deposit.upsert_pending(
            circle_transaction_id="txn-007",
            wallet=self.wallet,
            amount="100.00",
            network="ETHEREUM",
            circle_status="COMPLETED",
        )

        self.assertEqual(Deposit.objects.filter(circle_transaction_id="txn-007").count(), 1)

    def test_defaults_for_optional_fields(self):
        """from_address and transaction_hash default to empty strings."""
        deposit = Deposit.upsert_pending(
            circle_transaction_id="txn-008",
            wallet=self.wallet,
            amount="10.00",
            network="BASE",
            circle_status="INITIATED",
        )

        self.assertEqual(deposit.from_address, "")
        self.assertEqual(deposit.transaction_hash, "")

    def test_different_transaction_ids_create_separate_deposits(self):
        Deposit.upsert_pending(
            circle_transaction_id="txn-A",
            wallet=self.wallet,
            amount="10.00",
            network="ETHEREUM",
            circle_status="INITIATED",
        )
        Deposit.upsert_pending(
            circle_transaction_id="txn-B",
            wallet=self.wallet,
            amount="20.00",
            network="BASE",
            circle_status="CONFIRMED",
        )

        self.assertEqual(Deposit.objects.count(), 2)

    def test_unknown_status_treated_as_lowest_order(self):
        """A status not in CIRCLE_STATUS_ORDER gets order -1 and is overridden by any known status."""
        deposit = Deposit.objects.create(
            circle_transaction_id="txn-009",
            user=self.user,
            amount="50.00",
            network="ETHEREUM",
            circle_status="UNKNOWN_STATUS",
            paid_status=Deposit.PENDING,
        )

        result = Deposit.upsert_pending(
            circle_transaction_id="txn-009",
            wallet=self.wallet,
            amount="50.00",
            network="ETHEREUM",
            circle_status="INITIATED",
        )

        self.assertEqual(result.circle_status, "INITIATED")
