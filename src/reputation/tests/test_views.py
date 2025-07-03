import decimal
import re
import time
from datetime import datetime, timedelta
from unittest import mock

import requests_mock
from django.contrib.admin.models import LogEntry
from django.utils import timezone
from pytz import utc
from rest_framework.test import APITestCase

from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.lib import PendingWithdrawal
from reputation.models import Withdrawal
from reputation.tests.helpers import create_deposit, create_withdrawals
from reputation.views.withdrawal_view import WithdrawalViewSet
from user.related_models.user_verification_model import UserVerification
from user.rsc_exchange_rate_record_tasks import RSC_COIN_GECKO_ID
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation,
)
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_post_response,
)


def mocked_execute_erc20_transfer(w3, sender, sender_signing_key, contract, to, amount):
    return "tx_hash"


class ReputationViewsTests(APITestCase):
    def setUp(self):
        self.withdrawal_view = WithdrawalViewSet()
        create_withdrawals(10)
        self.all_withdrawals = len(Withdrawal.objects.all())
        self.mocker = requests_mock.Mocker()
        self.mocker.start()

        # Mock calls to etherscan
        etherscan_matcher = re.compile(
            r"https://api\.etherscan\.io/v2/api\?chainid=1.*"
        )
        self.mocker.get(etherscan_matcher, json={"result": {"SafeGasPrice": "30"}})

        # Mock calls to basescan
        basescan_matcher = re.compile(
            r"https://api\.etherscan\.io/v2/api\?chainid=8453.*"
        )
        self.mocker.get(basescan_matcher, json={"result": "0x38a5ef"})

        # Mock calls to coingecko
        coingecko_matcher = re.compile("https://api.coingecko.com/.*")
        self.mocker.get(
            coingecko_matcher, json={RSC_COIN_GECKO_ID: {"usd": 0.01, "eth": 0.0001}}
        )

        # Add mock for hotwallet balance
        self.hotwallet_patcher = mock.patch(
            "reputation.views.withdrawal_view.get_hotwallet_rsc_balance",
            return_value=1000000,  # Set a large enough balance for tests
        )
        self.hotwallet_patcher.start()

    def tearDown(self):
        self.mocker.stop()
        self.hotwallet_patcher.stop()  # Stop the hotwallet mock

    def test_deposit_user_can_list_deposits(self):
        user = create_random_authenticated_user("deposit_user")

        create_deposit(user)

        self.client.force_authenticate(user)
        response = self.client.get("/api/deposit/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_deposit_user_cannot_list_other_deposits(self):
        user = create_random_authenticated_user("deposit_user")
        other_user = create_random_authenticated_user("other_deposit_user")

        create_deposit(user)

        self.client.force_authenticate(other_user)
        response = self.client.get("/api/deposit/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_deposit_deposit_staff_user_can_list_all_deposits(self):
        user1 = create_random_authenticated_user("user1")
        user2 = create_random_authenticated_user("user2")
        staff_user = create_random_authenticated_user("staff_user1")
        staff_user.is_staff = True
        staff_user.save()

        create_deposit(user1)
        create_deposit(user2)

        self.client.force_authenticate(staff_user)
        response = self.client.get("/api/deposit/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_suspecious_user_cannot_withdraw_rsc(self):
        user = create_random_authenticated_user("rep_user")
        user.set_probable_spammer()
        self.client.force_authenticate(user)

        response = self.client.post(
            "/api/withdrawal/",
            {
                "agreed_to_terms": True,
                "amount": "333",
                "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "transaction_fee": 15,
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_regular_user_can_withdraw_rsc(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "transaction_fee": 15,
                },
            )
            self.assertEqual(response.status_code, 201)

    def test_verified_user_cannot_rewithdraw_rsc_within_24_hours(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )
        withdrawal = Withdrawal.objects.create(
            user=user,
            token_address="0x0123",
            amount="100",
            fee="10",
            from_address="0x0123",
            to_address="0x0123",
            transaction_hash="0x0123",
            paid_status="PAID",
        )

        withdrawal.created_date = timezone.now() - timedelta(hours=11)
        withdrawal.save()

        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "transaction_fee": 15,
                },
            )

            self.assertEqual(response.status_code, 400)

    def test_verified_user_can_rewithdraw_rsc_after_24_hours(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )
        withdrawal = Withdrawal.objects.create(
            user=user,
            token_address="0x0123",
            amount="100",
            fee="10",
            from_address="0x0123",
            to_address="0x0123",
            transaction_hash="0x0123",
            paid_status="PAID",
        )

        withdrawal.created_date = timezone.now() - timedelta(hours=25)
        withdrawal.save()

        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "transaction_fee": 15,
                },
            )
            self.assertEqual(response.status_code, 201)

    def test_unverified_user_cannot_rewithdraw_rsc_within_14_days(self):
        # Mock calls to etherscan
        etherscan_matcher = re.compile(r"https://api\.etherscan\.io/.*")
        # Mock with float to validate it doesn't throw.
        self.mocker.get(etherscan_matcher, json={"result": {"SafeGasPrice": "30.1"}})

        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        withdrawal = Withdrawal.objects.create(
            user=user,
            token_address="0x0123",
            amount="100",
            fee="10",
            from_address="0x0123",
            to_address="0x0123",
            transaction_hash="0x0123",
            paid_status="PAID",
        )

        withdrawal.created_date = timezone.now() - timedelta(days=13)
        withdrawal.save()

        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "transaction_fee": 15,
                },
            )

            self.assertEqual(response.status_code, 400)

    def test_verified_address_cannot_rewithdraw_rsc_within_24_hours(self):
        other_user = create_random_authenticated_user("other_user")
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )
        withdrawal = Withdrawal.objects.create(
            user=other_user,
            token_address="0x0123",
            amount="100",
            fee="10",
            from_address="0x0123",
            to_address="0x0123",
            transaction_hash="0x0123",
            paid_status="PAID",
        )

        withdrawal.created_date = timezone.now() - timedelta(hours=11)
        withdrawal.save()

        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0123",
                    "transaction_fee": 15,
                },
            )
            self.assertEqual(response.status_code, 400)

    def test_verified_address_can_rewithdraw_rsc_after_24_hours(self):
        other_user = create_random_authenticated_user("other_user")
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )
        withdrawal = Withdrawal.objects.create(
            user=other_user,
            token_address="0x0123",
            amount="100",
            fee="10",
            from_address="0x0123",
            to_address="0x0123",
            transaction_hash="0x0123",
            paid_status="PAID",
        )

        withdrawal.created_date = timezone.now() - timedelta(hours=25)
        withdrawal.save()

        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0123",
                    "transaction_fee": 15,
                },
            )

            self.assertEqual(response.status_code, 201)

    def test_new_verified_user_can_withdraw_rsc_immediately(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )
        withdrawal = Withdrawal.objects.create(
            user=user,
            token_address="0x0123",
            amount="100",
            fee="10",
            from_address="0x0123",
            to_address="0x0123",
            transaction_hash="0x0123",
            paid_status="PAID",
        )

        withdrawal.created_date = timezone.now() - timedelta(hours=25)
        withdrawal.save()

        user.date_joined = timezone.now()
        user.created_date = timezone.now()
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0123",
                    "transaction_fee": 15,
                },
            )

            self.assertEqual(response.status_code, 201)

    def test_user_can_NOT_withdraw_with_switch_on(self):
        moderator = user = create_random_authenticated_user("moderator", moderator=True)
        # Withdrawals are on
        LogEntry.objects.create(
            object_repr="WITHDRAWAL_SWITCH", action_flag=3, user=moderator
        )

        user = create_random_authenticated_user("withdrawal_user")
        distribution = Dist("REWARD", 1000000000, give_rep=False)

        distributor = Distributor(distribution, user, user, time.time(), user)
        distributor.distribute()
        user.reputation = 200
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        response = self.get_withdrawals_post_response(
            user, data={"amount": 505, "to_address": "0x0"}
        )
        self.assertEqual(response.status_code, 400)

    def test_can_withdraw_with_sufficient_reputation(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user1", 1000)

        # Act
        actual = self.withdrawal_view._can_withdraw(user)

        # Assert
        self.assertTrue(actual)

    def test_can_withdraw_with_verification(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user2", 0)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )

        # Act
        actual = self.withdrawal_view._can_withdraw(user)

        # Assert
        self.assertTrue(actual)

    def test_can_withdraw_fails_with_declined_status(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user2", 0)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.DECLINED
        )

        # Act
        actual = self.withdrawal_view._can_withdraw(user)

        # Assert
        self.assertFalse(actual)

    def test_can_withdraw_fails_without_verification_record(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user2", 0)

        # Act
        actual = self.withdrawal_view._can_withdraw(user)

        # Assert
        self.assertFalse(actual)

    def test_min_time_between_withdrawals_verified(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user2", 0)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        # Act
        actual = self.withdrawal_view._min_time_between_withdrawals(user)

        # Assert
        self.assertEqual(actual, timedelta(days=1))

    def test_min_time_between_withdrawals_non_verified(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user2", 0)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        # Act
        actual = self.withdrawal_view._min_time_between_withdrawals(user)

        # Assert
        self.assertEqual(actual, timedelta(days=14))

    def test_min_time_between_withdrawals_message_verified(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user2", 0)
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        # Act
        actual = self.withdrawal_view._min_time_between_withdrawals_message(user)

        # Assert
        self.assertEqual(actual, "You're limited to 1 withdrawal a day.")

    def test_min_time_between_withdrawals_message_non_verified(self):
        # Arrange
        user = create_random_authenticated_user_with_reputation("user2", 0)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        # Act
        actual = self.withdrawal_view._min_time_between_withdrawals_message(user)

        # Assert
        self.assertEqual(actual, "You're limited to 1 withdrawal every 2 weeks.")

    def test_withdrawal_fails_with_insufficient_hotwallet_balance(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        # Temporarily override the hotwallet balance mock to return insufficient funds
        with mock.patch(
            "reputation.views.withdrawal_view.get_hotwallet_rsc_balance",
            return_value=10,  # Set a small balance that won't cover the withdrawal
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "transaction_fee": 15,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.data, "Hotwallet balance is lower than the withdrawal amount"
            )

    def test_base_network_withdrawal_succeeds(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        with mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "transaction_fee": 15,
                    "network": "BASE",
                },
            )
            self.assertEqual(response.status_code, 201)
            withdrawal = Withdrawal.objects.get(id=response.data["id"])
            self.assertEqual(withdrawal.network, "BASE")

    def test_invalid_network_withdrawal_fails(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        response = self.client.post(
            "/api/withdrawal/",
            {
                "agreed_to_terms": True,
                "amount": "550",
                "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "transaction_fee": 15,
                "network": "INVALID",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data, "Invalid network. Please choose either 'BASE' or 'ETHEREUM'"
        )

    def test_base_network_withdrawal_fails_with_insufficient_hotwallet_balance(self):
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=utc)
        user.save()

        create_deposit(user)
        self.client.force_authenticate(user)

        # Temporarily override the hotwallet balance mock to return insufficient funds
        with mock.patch(
            "reputation.views.withdrawal_view.get_hotwallet_rsc_balance",
            return_value=10,  # Set a small balance that won't cover the withdrawal
        ):
            response = self.client.post(
                "/api/withdrawal/",
                {
                    "agreed_to_terms": True,
                    "amount": "550",
                    "to_address": "0x0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "transaction_fee": 15,
                    "network": "BASE",
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.data, "Hotwallet balance is lower than the withdrawal amount"
            )

    def test_base_network_transaction_fee_is_lower(self):
        """Test that Base network transaction fees are lower than Ethereum."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        self.client.force_authenticate(user)

        # Reset the mocker to clear existing mocks
        self.mocker.reset()

        # Mock etherscan response for Ethereum network with higher gas price
        etherscan_matcher = re.compile(
            r"https://api\.etherscan\.io/v2/api\?chainid=1.*"
        )
        self.mocker.get(etherscan_matcher, json={"result": {"SafeGasPrice": "30"}})

        # Get Ethereum network fee first
        eth_response = self.client.get("/api/withdrawal/transaction_fee/")
        eth_fee = eth_response.data

        # Reset and setup mock for Base network to use lower gas price in hex format
        self.mocker.reset()
        basescan_matcher = re.compile(
            r"https://api\.etherscan\.io/v2/api\?chainid=8453.*"
        )
        self.mocker.get(
            basescan_matcher, json={"result": "0x3b9aca00"}
        )  # 1 gwei in hex

        # Get Base network fee
        base_response = self.client.get(
            "/api/withdrawal/transaction_fee/",
            {"network": "BASE"},
        )
        base_fee = base_response.data

        # Base fee should be lower than Ethereum fee
        self.assertLess(base_fee, eth_fee)

        self.assertEqual(base_fee, decimal.Decimal("1.2"))

    """
    Helper methods
    """

    def get_withdrawals_get_response(self, user):
        url = "/api/withdrawal/"
        return get_authenticated_get_response(user, url)

    def get_withdrawals_post_response(self, user, data={}):
        url = "/api/withdrawal/"
        return get_authenticated_post_response(user, url, data)
