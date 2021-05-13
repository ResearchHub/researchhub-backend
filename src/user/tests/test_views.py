from django.test import TestCase

from discussion.tests.helpers import create_comment
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_patch_response
)


class UserViewsTests(TestCase):
    def setUp(self):
        pass

    def test_actions_route_responds_with_all_actions(self):
        user = create_random_authenticated_user('action_oriented_user')
        create_comment(created_by=user)
        response = self.get_actions_response(user)
        count = '"count":1'
        self.assertContains(response, count)
        content_type = '"content_type":"comment"'
        self.assertContains(response, content_type)

    def test_actions_route_responds_with_empty_results_without_actions(self):
        user = create_random_authenticated_user('inactive_user')
        response = self.get_actions_response(user)
        text = '"results":[]'
        self.assertContains(response, text)

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

    def get_actions_response(self, user):
        url = f'/api/user/{user.id}/actions/'
        return get_authenticated_get_response(user, url)
