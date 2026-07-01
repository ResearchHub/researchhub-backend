import random

from rest_framework.test import APITestCase

from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation,
)

from .helpers import build_hub_data, create_hub


class HubPermissionsTests(APITestCase):
    def setUp(self):
        self.random_generator = random.Random("discussion")
        self.base_url = "/api/"
        self.user = create_random_authenticated_user("hub_permissions")
        self.hub = create_hub()
        self.trouble_maker = create_random_authenticated_user("trouble_maker")

    def test_can_NOT_create_hub_below_minimum_reputation(self):
        user = create_random_authenticated_user_with_reputation(99, 99)
        response = self.get_hub_post_response(user)
        self.assertEqual(response.status_code, 403)

    def get_hub_post_response(self, user):
        url = self.base_url + "hub/"
        data = build_hub_data("Permission Hub")
        self.client.force_authenticate(user)
        return self.client.post(url, data, format="json")
