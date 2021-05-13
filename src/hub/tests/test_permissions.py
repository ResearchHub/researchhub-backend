import random

from django.test import TestCase

from .helpers import (
    build_hub_data,
    create_hub
)
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation
)
from utils.test_helpers import (
    get_authenticated_post_response
)


class HubPermissionsTests(TestCase):

    def setUp(self):
        SEED = 'discussion'
        self.random_generator = random.Random(SEED)
        self.base_url = '/api/'
        self.user = create_random_authenticated_user('hub_permissions')
        self.hub = create_hub()
        self.trouble_maker = create_random_authenticated_user('trouble_maker')

    def test_can_create_hub_with_minimum_reputation(self):
        user = create_random_authenticated_user_with_reputation(100, 100)
        response = self.get_hub_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_create_hub_below_minimum_reputation(self):
        user = create_random_authenticated_user_with_reputation(99, 99)
        response = self.get_hub_post_response(user)
        self.assertEqual(response.status_code, 403)

    def get_hub_post_response(self, user):
        url = self.base_url + 'hub/'
        data = build_hub_data('Permission Hub')
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
