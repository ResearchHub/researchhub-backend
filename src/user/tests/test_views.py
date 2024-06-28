import json
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase

from paper.openalex_util import process_openalex_works
from paper.related_models.paper_model import Paper
from user.tests.helpers import create_random_authenticated_user, create_user
from utils.openalex import OpenAlex
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_patch_response,
)


class UserApiTests(APITestCase):
    @patch.object(OpenAlex, "get_works")
    def test_add_publications_to_author(self, mock_get_works):
        with open("./paper/tests/openalex_author_works.json", "r") as works_file:
            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)

            user_with_published_works = create_user(
                first_name="Yang",
                last_name="Wang",
                email="random_author@researchhub.com",
            )

            self.client.force_authenticate(user_with_published_works)

            # Get author work Ids first
            openalex_api = OpenAlex()
            author_works, cursor = openalex_api.get_works()
            work_ids = [work["id"] for work in author_works]

            # Add publications to author
            url = f"/api/author/{user_with_published_works.author_profile.id}/add_publications/"
            response = self.client.post(
                url, {"openalex_ids": work_ids, "openalex_author_id": "A5068835581"}
            )

            # Verify at least one publication is created and credited to the author
            paper = Paper.objects.get(openalex_id=author_works[0].get("id"))
            self.assertEqual(
                paper.authors.filter(
                    id=user_with_published_works.author_profile.id
                ).exists(),
                True,
            )

    @patch.object(OpenAlex, "get_works")
    def test_add_publications_to_should_notify_author_when_done(self, mock_get_works):
        from notification.models import Notification

        with open("./paper/tests/openalex_author_works.json", "r") as works_file:
            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)

            user_with_published_works = create_user(
                first_name="Yang",
                last_name="Wang",
                email="random_author@researchhub.com",
            )

            self.client.force_authenticate(user_with_published_works)

            # Get author work Ids first
            openalex_api = OpenAlex()
            author_works, cursor = openalex_api.get_works()
            work_ids = [work["id"] for work in author_works]

            # Add publications to author
            url = f"/api/author/{user_with_published_works.author_profile.id}/add_publications/"
            response = self.client.post(
                url, {"openalex_ids": work_ids, "openalex_author_id": "A5068835581"}
            )

            self.assertEqual(
                Notification.objects.last().notification_type,
                Notification.PUBLICATIONS_ADDED,
            )


class UserViewsTests(TestCase):
    def setUp(self):
        pass

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

    @patch.object(OpenAlex, "get_authors")
    def test_get_author_profile_reputation(self, mock_get_authors):
        from paper.models import Paper

        works = None
        with open("./paper/tests/openalex_works.json", "r") as file:
            response = json.load(file)
            works = response.get("results")

        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(works)

            dois = [work.get("doi") for work in works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]

            papers = Paper.objects.filter(doi__in=dois)
            first_author = papers.first().authors.first()

            url = f"/api/author/{first_author.id}/profile/"
            response = self.client.get(
                url,
            )

            self.assertGreater(response.data["reputation"]["score"], 0)
            self.assertGreater(len(response.data["reputation_list"]), 0)

    @patch.object(OpenAlex, "get_authors")
    def test_author_overview(self, mock_get_authors):
        from paper.models import Paper

        works = None
        with open("./paper/tests/openalex_works.json", "r") as file:
            response = json.load(file)
            works = response.get("results")

        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(works)

            dois = [work.get("doi") for work in works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]

            papers = Paper.objects.filter(doi__in=dois)
            first_author = papers.first().authors.first()

            url = f"/api/author/{first_author.id}/overview/"
            response = self.client.get(
                url,
            )

            self.assertGreater(response.data["count"], 0)

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
