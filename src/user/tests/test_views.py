from django.test import TestCase
from rest_framework.test import APITestCase

from discussion.tests.helpers import create_comment
from user.tests.helpers import create_random_authenticated_user, create_user
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_patch_response,
)


class UserViewsTests(TestCase):
    def setUp(self):
        pass

    def test_actions_route_responds_with_all_actions(self):
        user = create_random_authenticated_user("action_oriented_user")
        create_comment(created_by=user)
        response = self.get_actions_response(user)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["content_type"], "discussion | comment"
        )

    def test_actions_route_responds_with_empty_results_without_actions(self):
        user = create_random_authenticated_user("inactive_user")
        response = self.get_actions_response(user)
        text = '"results":[]'
        self.assertContains(response, text)

    def test_set_has_seen_first_coin_modal(self):
        user = create_random_authenticated_user("first_coin_viewser")
        self.assertFalse(user.has_seen_first_coin_modal)

        url = "/api/user/has_seen_first_coin_modal/"
        response = get_authenticated_patch_response(
            user, url, data={}, content_type="application/json"
        )
        self.assertContains(
            response, 'has_seen_first_coin_modal":true', status_code=200
        )

        user.refresh_from_db()
        self.assertTrue(user.has_seen_first_coin_modal)

    def get_actions_response(self, user):
        url = f"/api/user/{user.id}/actions/"
        return get_authenticated_get_response(user, url)


class UserPopoverTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(
            first_name="bank", last_name="bank", email="bank@researchhub.com"
        )

    def test_popover_for_existing_user(self):
        res = self.client.get(f"/api/popover/{self.bank_user.id}/get_user/")
        data = res.data
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["first_name"], "bank")
        self.assertEqual(data["last_name"], "bank")

    def test_popover_for_nonexistant_user(self):
        res = self.client.get("/api/popover/1000/get_user/")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.data["detail"], "Not found.")
