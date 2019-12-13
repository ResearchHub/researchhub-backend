from django.test import TestCase

from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import get_authenticated_patch_response


class UserViewsTests(TestCase):
    def setUp(self):
        pass

    def test_set_has_seen_first_coin_modal(self):
        user = create_random_authenticated_user('first_coin_viewser')
        self.assertFalse(user.has_seen_first_coin_modal)

        url = '/api/user/has_seen_first_coin_modal/'
        response = get_authenticated_patch_response(
            user,
            url,
            data={},
            content_type='application/json'
        )
        self.assertContains(
            response,
            'has_seen_first_coin_modal":true',
            status_code=200
        )

        user.refresh_from_db()
        self.assertTrue(user.has_seen_first_coin_modal)
