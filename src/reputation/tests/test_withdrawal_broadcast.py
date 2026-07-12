from datetime import UTC, datetime
from decimal import Decimal
from unittest import mock

from celery.exceptions import Retry
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from purchase.models import Balance, RscExchangeRate
from reputation.lib import (
    WITHDRAWAL_MINIMUM,
    broadcast_withdrawal_transfer,
    check_pending_withdrawal,
    evaluate_transaction_hash,
)
from reputation.models import Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from reputation.tasks import broadcast_withdrawal
from reputation.tests.helpers import create_deposit
from reputation.tests.test_withdrawal_view import VALID_TEST_TO_ADDRESS
from reputation.views.withdrawal_view import WithdrawalViewSet
from user.tests.helpers import create_random_authenticated_user_with_reputation
from utils.test_helpers import AWSMockTransactionTestCase

TEST_RSC_CONTRACT_ADDRESS = "0x1234567890123456789012345678901234567890"
TEST_WEB3_WALLET_ADDRESS = "0x0987654321098765432109876543210987654321"


class EvaluateTransactionHashTests(AWSMockTransactionTestCase):
    def test_none_hash_returns_pending_without_web3(self):
        with mock.patch("reputation.lib.web3_provider") as mock_provider:
            paid_status, paid_date = evaluate_transaction_hash(None, network="ETHEREUM")

        self.assertEqual(paid_status, PaidStatusModelMixin.PENDING)
        self.assertIsNone(paid_date)
        mock_provider.ethereum.eth.wait_for_transaction_receipt.assert_not_called()

    @mock.patch("reputation.lib.web3_provider")
    def test_reverted_receipt_returns_failed(self, mock_provider):
        mock_provider.ethereum.eth.wait_for_transaction_receipt.return_value = {
            "status": 0
        }

        paid_status, paid_date = evaluate_transaction_hash(
            "0xfailed", network="ETHEREUM"
        )

        self.assertEqual(paid_status, PaidStatusModelMixin.FAILED)
        self.assertIsNone(paid_date)


class BroadcastWithdrawalTransferTests(AWSMockTransactionTestCase):
    def setUp(self):
        self.user = create_random_authenticated_user_with_reputation(
            "broadcast_user", 1000
        )
        create_deposit(self.user, amount="2000.0")
        self.initial_balance = self.user.get_balance()

    def _create_withdrawal_with_balance(
        self,
        amount="500",
        fee="10",
        paid_status=PaidStatusModelMixin.INITIATED,
        transaction_hash=None,
    ):
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            token_address="0xtoken",
            from_address="0xfrom",
            to_address="0xto",
            amount=amount,
            fee=fee,
            network="ETHEREUM",
            paid_status=paid_status,
            transaction_hash=transaction_hash,
        )
        withdrawal_content_type = ContentType.objects.get_for_model(Withdrawal)
        Balance.objects.create(
            user=self.user,
            content_type=withdrawal_content_type,
            object_id=withdrawal.id,
            amount=f"-{Decimal(amount) + Decimal(fee)}",
        )
        return withdrawal

    @override_settings(
        WEB3_WALLET_ADDRESS=TEST_WEB3_WALLET_ADDRESS,
        WEB3_KEYSTORE_SECRET_ID="mock-secret-id",
    )
    @mock.patch("reputation.lib.RSC_CONTRACT_ADDRESS", TEST_RSC_CONTRACT_ADDRESS)
    @mock.patch("reputation.lib.execute_erc20_transfer", return_value="0xabc")
    @mock.patch("reputation.lib.get_nonce", return_value=7)
    @mock.patch("reputation.lib.get_private_key", return_value="mock-key")
    def test_broadcast_sets_hash_and_pending(
        self, mock_get_private_key, mock_nonce, mock_transfer
    ):
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
        self.assertEqual(mock_transfer.call_args.args[2], "mock-key")
        self.assertEqual(mock_transfer.call_args.kwargs["nonce"], 7)
        mock_get_private_key.assert_called_once_with()

    @mock.patch("reputation.lib.get_private_key")
    @mock.patch("reputation.lib.execute_erc20_transfer")
    def test_broadcast_skips_when_hash_already_set(
        self, mock_transfer, mock_get_private_key
    ):
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
        mock_get_private_key.assert_not_called()

    @mock.patch("reputation.tasks.logger")
    @mock.patch("reputation.tasks.broadcast_withdrawal.retry")
    @mock.patch("reputation.tasks.broadcast_withdrawal_transfer")
    def test_broadcast_withdrawal_failure_handling(
        self, mock_transfer, mock_retry, mock_logger
    ):
        mock_transfer.side_effect = Exception("RPC unavailable")

        withdrawal = self._create_withdrawal_with_balance()
        mock_retry.side_effect = Retry()
        with self.assertRaises(Retry):
            broadcast_withdrawal(withdrawal.id)

        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.paid_status, PaidStatusModelMixin.INITIATED)
        self.assertEqual(self.user.get_balance(), self.initial_balance - Decimal(510))

        with mock.patch.object(
            broadcast_withdrawal.request,
            "retries",
            broadcast_withdrawal.max_retries,
        ):
            self.assertFalse(broadcast_withdrawal(withdrawal.id))

        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.paid_status, PaidStatusModelMixin.FAILED)
        self.assertEqual(self.user.get_balance(), self.initial_balance)

        pending_with_hash = self._create_withdrawal_with_balance(
            paid_status=PaidStatusModelMixin.PENDING,
            transaction_hash="0xsubmitted",
        )
        with mock.patch.object(
            broadcast_withdrawal.request,
            "retries",
            broadcast_withdrawal.max_retries,
        ):
            self.assertFalse(broadcast_withdrawal(pending_with_hash.id))

        pending_with_hash.refresh_from_db()
        self.assertEqual(pending_with_hash.paid_status, PaidStatusModelMixin.PENDING)
        self.assertEqual(self.user.get_balance(), self.initial_balance - Decimal(510))


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
        self.requests_get_patcher = mock.patch("requests.get")
        self.mock_requests_get = self.requests_get_patcher.start()
        eth_mock_response = mock.MagicMock()
        eth_mock_response.json.return_value = {"result": {"SafeGasPrice": "30"}}
        self.mock_requests_get.return_value = eth_mock_response

        self.settings_patcher = mock.patch.object(
            settings,
            "WEB3_KEYSTORE_SECRET_ID",
            new_callable=mock.PropertyMock,
            return_value="mock-secret-id",
        )
        self.settings_patcher.start()

        self.eth_to_rsc_patcher = mock.patch.object(
            RscExchangeRate, "eth_to_rsc", return_value=10
        )
        self.eth_to_rsc_patcher.start()
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5)

        self.user = create_random_authenticated_user_with_reputation(
            "on_commit_user", 1000
        )
        self.user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=UTC)
        self.user.created_date = datetime(year=2020, month=1, day=1, tzinfo=UTC)
        self.user.save()
        create_deposit(self.user, amount="5000.0")

    def tearDown(self):
        self.eth_to_rsc_patcher.stop()
        self.settings_patcher.stop()
        self.requests_get_patcher.stop()

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
                "amount": str(WITHDRAWAL_MINIMUM + 10),
                "to_address": VALID_TEST_TO_ADDRESS,
                "network": "ETHEREUM",
            },
        )

        self.assertEqual(response.status_code, 201, response.data)
        withdrawal = Withdrawal.objects.get(id=response.data["id"])
        self.assertEqual(withdrawal.paid_status, PaidStatusModelMixin.INITIATED)
        mock_delay.assert_called_once_with(withdrawal.id)

        balance = Balance.objects.get(
            content_type=ContentType.objects.get_for_model(Withdrawal),
            object_id=withdrawal.id,
        )
        self.assertEqual(
            balance.amount, f"-{Decimal(withdrawal.amount) + Decimal(withdrawal.fee)}"
        )
