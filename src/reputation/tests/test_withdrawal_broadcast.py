from decimal import Decimal
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from purchase.models import Balance
from reputation.lib import (
    broadcast_withdrawal_transfer,
    check_pending_withdrawal,
    evaluate_transaction_hash,
)
from reputation.models import Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from reputation.tests.helpers import create_deposit
from reputation.views.withdrawal_view import WithdrawalViewSet
from user.tests.helpers import create_random_authenticated_user_with_reputation
from utils.test_helpers import AWSMockTransactionTestCase


class EvaluateTransactionHashTests(AWSMockTransactionTestCase):
    def test_none_hash_returns_pending_without_web3(self):
        with mock.patch("reputation.lib.web3_provider") as mock_provider:
            paid_status, paid_date = evaluate_transaction_hash(None, network="ETHEREUM")

        self.assertEqual(paid_status, PaidStatusModelMixin.PENDING)
        self.assertIsNone(paid_date)
        mock_provider.ethereum.eth.wait_for_transaction_receipt.assert_not_called()


class BroadcastWithdrawalTransferTests(AWSMockTransactionTestCase):
    def setUp(self):
        self.user = create_random_authenticated_user_with_reputation(
            "broadcast_user", 1000
        )
        create_deposit(self.user, amount="2000.0")

    @mock.patch("reputation.lib.execute_erc20_transfer", return_value="0xabc")
    @mock.patch("reputation.lib.get_nonce", return_value=7)
    @mock.patch("reputation.lib.PRIVATE_KEY", "mock-key")
    def test_broadcast_sets_hash_and_pending(self, mock_nonce, mock_transfer):
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            token_address="0xtoken",
            from_address="0xfrom",
            to_address="0xto",
            amount="500",
            fee="10",
            network="ETHEREUM",
            paid_status=PaidStatusModelMixin.INITIATED,
        )

        broadcast_withdrawal_transfer(withdrawal)

        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.transaction_hash, "0xabc")
        self.assertEqual(withdrawal.paid_status, PaidStatusModelMixin.PENDING)
        self.assertEqual(withdrawal.broadcast_nonce, 7)
        mock_transfer.assert_called_once()
        self.assertEqual(mock_transfer.call_args.kwargs["nonce"], 7)

    @mock.patch("reputation.lib.execute_erc20_transfer")
    def test_broadcast_skips_when_hash_already_set(self, mock_transfer):
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            token_address="0xtoken",
            from_address="0xfrom",
            to_address="0xto",
            amount="500",
            fee="10",
            network="ETHEREUM",
            paid_status=PaidStatusModelMixin.PENDING,
            transaction_hash="0xexisting",
            broadcast_nonce=3,
        )

        broadcast_withdrawal_transfer(withdrawal)

        mock_transfer.assert_not_called()


class CheckPendingWithdrawalRecoveryTests(AWSMockTransactionTestCase):
    @mock.patch("reputation.tasks.broadcast_withdrawal.delay")
    def test_stuck_initiated_enqueues_broadcast(self, mock_delay):
        withdrawal = Withdrawal.objects.create(
            user=create_random_authenticated_user_with_reputation("stuck_user", 100),
            token_address="0xtoken",
            from_address="0xfrom",
            to_address="0xto",
            amount="100",
            fee="10",
            network="ETHEREUM",
            paid_status=PaidStatusModelMixin.INITIATED,
        )

        check_pending_withdrawal()

        mock_delay.assert_called_once_with(withdrawal.id)

    @mock.patch("reputation.tasks.broadcast_withdrawal.delay")
    def test_pending_without_hash_enqueues_broadcast(self, mock_delay):
        withdrawal = Withdrawal.objects.create(
            user=create_random_authenticated_user_with_reputation(
                "stuck_pending_user", 100
            ),
            token_address="0xtoken",
            from_address="0xfrom",
            to_address="0xto",
            amount="100",
            fee="10",
            network="ETHEREUM",
            paid_status=PaidStatusModelMixin.PENDING,
            transaction_hash=None,
        )

        check_pending_withdrawal()

        mock_delay.assert_called_once_with(withdrawal.id)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class WithdrawalOnCommitTests(AWSMockTransactionTestCase):
    def setUp(self):
        self.user = create_random_authenticated_user_with_reputation(
            "on_commit_user", 1000
        )
        create_deposit(self.user, amount="5000.0")

    @mock.patch("reputation.tasks.broadcast_withdrawal.delay")
    @mock.patch.object(
        WithdrawalViewSet, "_check_hotwallet_balance", return_value=(True, None)
    )
    def test_broadcast_scheduled_after_commit(self, mock_hotwallet, mock_delay):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            "/api/withdrawal/",
            {
                "amount": "600",
                "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            },
        )

        self.assertEqual(response.status_code, 201)
        withdrawal = Withdrawal.objects.get(id=response.data["id"])
        self.assertEqual(withdrawal.paid_status, PaidStatusModelMixin.INITIATED)
        mock_delay.assert_called_once_with(withdrawal.id)

        balance = Balance.objects.get(
            content_type=ContentType.objects.get_for_model(Withdrawal),
            object_id=withdrawal.id,
        )
        self.assertEqual(balance.amount, f"-{Decimal(withdrawal.amount) + Decimal(withdrawal.fee)}")
