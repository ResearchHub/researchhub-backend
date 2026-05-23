import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase

from purchase.circle.service import process_circle_deposit
from purchase.models import Balance, Wallet
from reputation.models import Deposit

User = get_user_model()


class TestProcessCircleDeposit(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="circle_depositor")
        self.wallet = Wallet.objects.create(
            user=self.user,
            circle_wallet_id="wallet-eth",
            circle_base_wallet_id="wallet-base",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
            address="0xDepositor",
        )

    def test_concurrent_completed_webhooks_credit_once(self):
        """
        Two concurrent COMPLETED handlers for the same pending deposit must
        credit the user only once.
        """
        Deposit.objects.create(
            user=self.user,
            amount="100",
            network="BASE",
            from_address="0xFrom",
            circle_transaction_id="tx-race-001",
            paid_status=Deposit.PENDING,
            circle_status=Deposit.CIRCLE_CONFIRMED,
        )

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def _credit():
            connection.close()
            try:
                barrier.wait(timeout=5)
                deposit, credited = process_circle_deposit(
                    circle_transaction_id="tx-race-001",
                    wallet=self.wallet,
                    amount="100",
                    network="BASE",
                )
                results.append(credited)
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_credit) for _ in range(2)]
            for future in as_completed(futures):
                future.result()

        self.assertEqual(errors, [])
        self.assertEqual(sum(1 for credited in results if credited), 1)
        self.assertEqual(
            Balance.objects.filter(user=self.user, amount="100").count(),
            1,
        )
        deposit = Deposit.objects.get(circle_transaction_id="tx-race-001")
        self.assertEqual(deposit.paid_status, Deposit.PAID)

    def test_completed_after_failed_does_not_credit(self):
        Deposit.objects.create(
            user=self.user,
            amount="50",
            network="BASE",
            from_address="0xFrom",
            circle_transaction_id="tx-failed-001",
            paid_status=Deposit.FAILED,
            circle_status=Deposit.CIRCLE_FAILED,
        )

        deposit, credited = process_circle_deposit(
            circle_transaction_id="tx-failed-001",
            wallet=self.wallet,
            amount="50",
            network="BASE",
        )

        self.assertFalse(credited)
        self.assertEqual(deposit.paid_status, Deposit.FAILED)
        self.assertFalse(Balance.objects.filter(user=self.user).exists())
