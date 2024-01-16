import time
from datetime import datetime
from unittest import skip

from django.contrib.admin.models import LogEntry
from pytz import utc
from rest_framework.test import APITestCase

from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Withdrawal
from reputation.tests.helpers import create_withdrawals
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_post_response,
)


class ReputationViewsTests(APITestCase):
    def setUp(self):
        create_withdrawals(10)
        self.all_withdrawals = len(Withdrawal.objects.all())

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
        user = create_random_authenticated_user("rep_user")
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

        self.assertNotEqual(response.status_code, 403)

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

    """
    Helper methods
    """

    def get_withdrawals_get_response(self, user):
        url = "/api/withdrawal/"
        return get_authenticated_get_response(user, url)

    def get_withdrawals_post_response(self, user, data={}):
        url = "/api/withdrawal/"
        return get_authenticated_post_response(user, url, data)
