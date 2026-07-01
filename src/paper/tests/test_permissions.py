import random

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from user.models import Author
from user.tests.helpers import create_random_authenticated_user, create_university

from .helpers import create_paper


class PaperPermissionsIntegrationTests(APITestCase):
    def setUp(self):
        self.random_generator = random.Random("paper")
        self.base_url = "/api/paper/"
        self.paper = create_paper()
        self.flag_reason = "Inappropriate"

    def test_can_not_post_paper_below_minimum_reputation(self):
        user = self.create_user_with_reputation(-1)
        response = self.get_paper_submission_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_flag_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(50)
        response = self.get_flag_response(user)
        self.assertContains(response, self.flag_reason, status_code=201)

    def test_can_update_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_patch_response(user, self.paper)
        self.assertEqual(response.status_code, 200)

    def test_can_not_update_paper_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_patch_response(user, self.paper)
        self.assertEqual(response.status_code, 403)

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

    def get_paper_submission_response(self, user):
        url = self.base_url
        form_data = self.build_paper_form()
        self.client.force_authenticate(user)
        return self.client.post(url, form_data, format="multipart")

    def get_patch_response(self, user, paper):
        if paper is None:
            paper = self.paper
        url = self.base_url + f"{paper.id}/"
        data = {"title": "Patched Paper Title"}
        self.client.force_authenticate(user)
        return self.client.patch(url, data, format="multipart")

    def build_paper_form(self):
        file = SimpleUploadedFile("../config/paper.pdf", b"file_content")
        hub = create_hub("Cryptography")
        university = create_university(name="Univeristy of Atlanta")
        author = Author.objects.create(
            university=university, first_name="Tom", last_name="Riddle"
        )
        form = {
            "title": "The Best Paper",
            "paper_publish_date": "1990-10-01",
            "file": file,
            "hubs": [hub.id],
            "authors": [1, author.id],
        }
        return form

    def get_flag_response(self, user):
        url = self.base_url + f"{self.paper.id}/flag/"
        data = {"reason": self.flag_reason, "reason_choice": "SPAM"}
        self.client.force_authenticate(user)
        return self.client.post(url, data, format="json")

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
