import random

from rest_framework.test import APITestCase

from user.tests.helpers import create_random_authenticated_user

from .helpers import create_paper


class PaperPermissionsIntegrationTests(APITestCase):
    def setUp(self):
        self.random_generator = random.Random("paper")
        self.base_url = "/api/paper/"
        self.paper = create_paper()

    def test_can_upvote_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_upvote_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_downvote_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(25)
        response = self.get_downvote_response(user)
        self.assertEqual(response.status_code, 201)

    def create_user_with_reputation(self, reputation):
        unique_value = self.random_generator.random()
        user = create_random_authenticated_user(unique_value)
        user.reputation = reputation
        user.save()
        return user

    def get_upvote_response(self, user):
        url = self.base_url + f"{self.paper.id}/upvote/"
        data = {}
        self.client.force_authenticate(user)
        return self.client.post(url, data, format="json")

    def get_downvote_response(self, user):
        url = self.base_url + f"{self.paper.id}/downvote/"
        data = {}
        self.client.force_authenticate(user)
        return self.client.post(url, data, format="json")
