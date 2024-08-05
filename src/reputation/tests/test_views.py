import re
import time
from datetime import datetime, timedelta
from unittest import mock, skip

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
        etherscan_matcher = re.compile("https://api.etherscan.io/.*")
        self.mocker.get(etherscan_matcher, json={"result": {"SafeGasPrice": "30"}})

        # Mock calls to coingecko
        coingecko_matcher = re.compile("https://api.coingecko.com/.*")
        self.mocker.get(
            coingecko_matcher, json={RSC_COIN_GECKO_ID: {"usd": 0.01, "eth": 0.0001}}
        )

    def tearDown(self):
        self.mocker.stop()

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

        withdrawal.created_date = timezone.now() - timedelta(hours=23)
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

    @skip
    def test_user_can_only_see_own_withdrawals(self):
        user = create_random_authenticated_user("rep_user")
        user_withdrawals = user.withdrawals.count()
        response = self.get_withdrawals_get_response(user)
        self.assertGreater(self.all_withdrawals, user_withdrawals)
        self.assertContains(response, '"results":[]', status_code=200)

    @skip
    def test_user_can_NOT_withdraw_below_minimum(self):
        user = create_random_authenticated_user("new_user")
        response = self.get_withdrawals_post_response(user)
        self.assertContains(response, "25", status_code=400)

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

    """
    Helper methods
    """

    def get_withdrawals_get_response(self, user):
        url = "/api/withdrawal/"
        return get_authenticated_get_response(user, url)

    def get_withdrawals_post_response(self, user, data={}):
        url = "/api/withdrawal/"
        return get_authenticated_post_response(user, url, data)
