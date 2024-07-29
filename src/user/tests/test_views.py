import json
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase

from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from reputation.models import Score
from user.models import UserVerification
from user.tests.helpers import create_random_authenticated_user, create_user
from utils.openalex import OpenAlex
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_patch_response,
)


class UserApiTests(APITestCase):
    def setUp(self):
        self.user_with_published_works = create_user(
            email="random@researchhub.com",
            first_name="Yang",
            last_name="Wang",
        )
        UserVerification.objects.create(
            user=self.user_with_published_works,
            status=UserVerification.Status.APPROVED,
        )
        self.author_openalex_id = "https://openalex.org/A5068835581"
        # By setting the author profile to this openalex id, we can later test that
        # papers processed with matching author id will be attributed to this author.
        # This is typically done via claim process.
        self.user_with_published_works.author_profile.openalex_ids = [
            self.author_openalex_id
        ]
        self.user_with_published_works.author_profile.save()

    @patch.object(OpenAlex, "get_works")
    def test_add_publications_to_author(self, mock_get_works):
        with open("./paper/tests/openalex_author_works.json", "r") as works_file:
            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)

            self.client.force_authenticate(self.user_with_published_works)

            # Get author work Ids first
            openalex_api = OpenAlex()
            author_works, _ = openalex_api.get_works()
            work_ids = [work["id"] for work in author_works]

            # Add publications to author
            url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
            self.client.post(
                url,
                {
                    "openalex_ids": work_ids,
                    "openalex_author_id": self.author_openalex_id,
                },
            )

            # Verify at least one publication is created and credited to the author
            paper = Paper.objects.get(openalex_id=author_works[0].get("id"))
            self.assertEqual(
                paper.authors.filter(
                    id=self.user_with_published_works.author_profile.id
                ).exists(),
                True,
            )

    def test_delete_publications(self):
        # Arrange
        self.client.force_authenticate(self.user_with_published_works)

        paper1 = Paper.objects.create(
            title="title1",
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper1
        )
        paper2 = Paper.objects.create(
            title="title2",
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper2
        )

        # Act
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
        resp = self.client.delete(url, {"paper_ids": [paper1.id, paper2.id]})

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)
        self.assertFalse(
            Authorship.objects.filter(
                author=self.user_with_published_works.author_profile,
                paper__id__in=[paper1.id, paper2.id],
            ).exists()
        )

    def test_delete_publications_paper_not_found(self):
        # Arrange
        self.client.force_authenticate(self.user_with_published_works)

        # Act
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
        resp = self.client.delete(url, {"paper_ids": [-1]})

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_delete_publications_attempt_with_other_user(self):
        # Arrange
        other_user = create_user(
            email="email1@researchhub.com",
            first_name="firstName1",
            last_name="lastName1",
        )
        self.client.force_authenticate(other_user)

        paper = Paper.objects.create(
            title="title1",
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper
        )

        # Act
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
        resp = self.client.delete(url, {"paper_ids": [paper.id]})

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)
        self.assertTrue(
            Authorship.objects.filter(
                author=self.user_with_published_works.author_profile, paper=paper
            ).exists()
        )

    @patch.object(OpenAlex, "get_works")
    def test_add_publications_to_should_notify_author_when_done(self, mock_get_works):
        from notification.models import Notification

        with open("./paper/tests/openalex_author_works.json", "r") as works_file:
            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)

            self.client.force_authenticate(self.user_with_published_works)

            # Get author work Ids first
            openalex_api = OpenAlex()
            author_works, _ = openalex_api.get_works()
            work_ids = [work["id"] for work in author_works]

            # Add publications to author
            url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
            self.client.post(
                url,
                {
                    "openalex_ids": work_ids,
                    "openalex_author_id": self.author_openalex_id,
                },
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

            hub1 = papers.first().hubs.first()
            hub2 = papers.last().hubs.first()

            Score.objects.create(
                author=first_author,
                hub=hub1,
                version=1,
                score=1900,
            )

            Score.objects.create(
                author=first_author,
                hub=hub2,
                version=1,
                score=1800,
            )

            url = f"/api/author/{first_author.id}/profile/"
            response = self.client.get(
                url,
            )

            self.assertEqual(response.data["reputation"]["score"], 1900)
            self.assertEqual(response.data["reputation"]["percentile"], 0.275)
            self.assertEqual(response.data["reputation_list"][0]["score"], 1900)
            self.assertEqual(response.data["reputation_list"][0]["percentile"], 0.275)
            self.assertEqual(response.data["reputation_list"][1]["score"], 1800)
            self.assertEqual(
                response.data["reputation_list"][1]["percentile"], 0.2722222222222222
            )

    @patch.object(OpenAlex, "get_authors")
    def test_get_author_profile_no_reputation(self, mock_get_authors):
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

            self.assertIsNone(response.data["reputation"])
            self.assertEqual(len(response.data["reputation_list"]), 0)

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

    def test_popover_for_invalid_id(self):
        res = self.client.get("/api/popover/INVALID/get_user/")
        self.assertEqual(res.status_code, 404)
