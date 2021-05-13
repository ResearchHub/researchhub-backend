from rest_framework.test import APITestCase

from reputation.models import Withdrawal
from reputation.tests.helpers import create_withdrawals
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_post_response
)


class ReputationViewsTests(APITestCase):
    def setUp(self):
        create_withdrawals(10)
        self.all_withdrawals = len(Withdrawal.objects.all())

    def test_user_can_only_see_own_withdrawals(self):
        user = create_random_authenticated_user('rep_user')
        user_withdrawals = user.withdrawals.count()
        response = self.get_withdrawals_get_response(user)
        self.assertGreater(self.all_withdrawals, user_withdrawals)
        self.assertContains(response, '"results":[]', status_code=200)

    def test_user_can_NOT_withdraw_below_minimum(self):
        user = create_random_authenticated_user('new_user')
        response = self.get_withdrawals_post_response(user)
        self.assertContains(response, '25', status_code=400)

    def get_withdrawals_get_response(self, user):
        url = '/api/withdrawal/'
        return get_authenticated_get_response(
            user,
            url
        )

    def get_withdrawals_post_response(self, user):
        url = '/api/withdrawal/'
        return get_authenticated_post_response(
            user,
            url,
            {}
        )
