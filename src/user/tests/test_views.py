import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APITestCase

from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from reputation.models import Score
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import UserVerification
from user.related_models.author_model import Author
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
    create_random_default_user,
    create_user,
)
from utils.openalex import OpenAlex
from utils.test_helpers import get_authenticated_patch_response


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

    def test_get_publications(self):
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
        resp = self.client.get(url)

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_get_publications_writes_to_cache(self):
        # Arrange
        self.client.force_authenticate(self.user_with_published_works)

        paper = Paper.objects.create(
            title="title1",
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper
        )

        # Act
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
        resp = self.client.get(url)

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)
        cache_key = (
            f"author-{self.user_with_published_works.author_profile.id}-publications"
        )
        self.assertEqual(cache.get(cache_key)[0].paper, paper)

    def test_get_publications_reads_from_cache(self):
        # Arrange
        self.client.force_authenticate(self.user_with_published_works)

        document = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        Paper.objects.create(title="title1", unified_document=document)

        cache_key = (
            f"author-{self.user_with_published_works.author_profile.id}-publications"
        )
        cache.set(cache_key, [document])

        # Act
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
        resp = self.client.get(url)

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)
        self.assertEqual(
            resp.json()["results"][0]["documents"]["id"], document.paper.id
        )

    @patch.object(OpenAlex, "get_works")
    @patch.object(OpenAlex, "get_authors")
    def test_add_publications_to_author(self, mock_get_authors, mock_get_works):
        with open(
            "./user/tests/test_files/openalex_author_works.json", "r"
        ) as works_file:
            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)

            # Add mock for get_authors
            mock_get_authors.return_value = (mock_data["results"], None)

            self.client.force_authenticate(self.user_with_published_works)

            # Get author work Ids first
            openalex_api = OpenAlex()
            author_works, _ = openalex_api.get_works()
            work_ids = [work["id"] for work in author_works]

            # Add publications to author
            url = f"/api/author/{self.user_with_published_works.author_profile.id}/publications/"
            response = self.client.post(
                url,
                {
                    "openalex_ids": work_ids,
                    "openalex_author_id": self.author_openalex_id,
                },
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
    @patch.object(OpenAlex, "get_authors")
    def _add_publications_to_author(self, author, mock_get_authors, mock_get_works):
        with open(
            "./user/tests/test_files/openalex_author_works.json", "r"
        ) as works_file:
            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)

            # Add mock for get_authors
            mock_get_authors.return_value = (mock_data["results"], None)

            self.client.force_authenticate(self.user_with_published_works)

            # Get author work Ids first
            openalex_api = OpenAlex()
            author_works, _ = openalex_api.get_works()
            work_ids = [work["id"] for work in author_works]

            # Add publications to author
            url = f"/api/author/{author.id}/publications/"
            response = self.client.post(
                url,
                {
                    "openalex_ids": work_ids,
                    "openalex_author_id": self.author_openalex_id,
                },
            )

    def test_add_publications_to_should_notify_author_when_done(self):
        from notification.models import Notification

        self._add_publications_to_author(
            self.user_with_published_works.author_profile,
        )

        self.assertEqual(
            Notification.objects.last().notification_type,
            Notification.PUBLICATIONS_ADDED,
        )


class UserViewsTests(TestCase):
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

    def test_get_author_profile_user(self):
        # Arrange
        user = create_random_default_user("user1")
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )

        # Act
        url = f"/api/author/{user.author_profile.id}/profile/"
        response = self.client.get(url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["user"],
            {
                "id": user.id,
                "created_date": user.created_date,
                "is_verified": True,
                "is_suspended": False,
                "probable_spammer": False,
                "sift_url": f"https://console.sift.com/users/{user.id}?abuse_type=content_abuse",
            },
        )

    def test_get_author_profile_user_without_user(self):
        # Arrange
        author = Author.objects.create(first_name="firstName1", last_name="lastName1")

        # Act
        url = f"/api/author/{author.id}/profile/"
        response = self.client.get(url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"], None)

    @patch.object(OpenAlex, "get_authors")
    def test_get_author_profile_reputation(self, mock_get_authors):
        from paper.models import Paper

        works = None
        with open("./user/tests/test_files/openalex_works.json", "r") as file:
            response = json.load(file)
            works = response.get("results")

        with open("./user/tests/test_files/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(works)

            dois = [work.get("doi") for work in works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]

            papers = Paper.objects.filter(doi__in=dois)
            first_author = papers.first().authors.first()

            hub1 = papers.first().hubs.first()
            hub2 = papers.last().hubs.first()
            hub3 = papers.first().hubs.last()

            Score.objects.create(
                author=first_author,
                hub=hub1,
                score=1900,
            )

            Score.objects.create(
                author=first_author,
                hub=hub2,
                score=1800,
            )

            Score.objects.create(
                author=first_author,
                hub=hub3,
                score=0,
            )

            url = f"/api/author/{first_author.id}/profile/"
            response = self.client.get(
                url,
            )

            self.assertEqual(
                len(response.data["reputation_list"]), 2
            )  # Filter out 0 scores
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
        with open("./user/tests/test_files/openalex_works.json", "r") as file:
            response = json.load(file)
            works = response.get("results")

        with open("./user/tests/test_files/openalex_authors.json", "r") as file:
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
        with open("./user/tests/test_files/openalex_works.json", "r") as file:
            response = json.load(file)
            works = response.get("results")

        with open("./user/tests/test_files/openalex_authors.json", "r") as file:
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

    @patch.object(OpenAlex, "get_authors")
    def test_author_overview_writes_to_cache(self, mock_get_authors):
        # Arrange
        from paper.models import Paper

        works = None
        with open("./user/tests/test_files/openalex_works.json", "r") as file:
            response = json.load(file)
            works = response.get("results")

        with open("./user/tests/test_files/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(works)

            dois = [work.get("doi") for work in works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]

            papers = Paper.objects.filter(doi__in=dois)
            first_author = papers.first().authors.first()

            # Act
            url = f"/api/author/{first_author.id}/overview/"
            response = self.client.get(
                url,
            )

            # Assert
            self.assertTrue(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
            cache_key = f"author-{first_author.id}-overview"
            self.assertTrue(cache.get(cache_key))
            self.assertEqual(len(cache.get(cache_key)), 1)

    def test_author_overview_returns_from_cache(self):
        # Arrange
        author = Author.objects.create(first_name="firstName1", last_name="lastName1")

        document = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        Paper.objects.create(title="title1", unified_document=document)

        cache_key = f"author-{author.id}-overview"
        cache.set(cache_key, [document])

        # Act
        url = f"/api/author/{author.id}/overview/"
        response = self.client.get(
            url,
        )

        # Assert
        self.assertTrue(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["results"][0]["documents"]["id"], document.paper.id
        )


class UserModerationTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.target_user = create_random_authenticated_user("target_user")
        [self.hub_editor, self.hub] = create_hub_editor("hub_editor", "test_hub")

    def test_mark_probable_spammer_success(self):
        url = "/api/user/mark_probable_spammer/"
        data = {"authorId": self.target_user.author_profile.id}
        self.client.force_authenticate(user=self.moderator)
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.target_user.refresh_from_db()
        self.assertTrue(self.target_user.probable_spammer)
        self.assertFalse(self.target_user.is_suspended)
        self.assertTrue(self.target_user.is_active)

    def test_mark_probable_spammer_hub_editor_success(self):
        """Test that hub editors can mark users as probable spammers"""
        url = "/api/user/mark_probable_spammer/"
        data = {"authorId": self.target_user.author_profile.id}
        self.client.force_authenticate(user=self.hub_editor)
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.target_user.refresh_from_db()
        self.assertTrue(self.target_user.probable_spammer)
        self.assertFalse(self.target_user.is_suspended)
        self.assertTrue(self.target_user.is_active)

    def test_mark_probable_spammer_requires_moderator_or_editor(self):
        """Test that only moderators or hub editors can mark users as probable spammers"""
        regular_user = create_random_default_user("regular_user")
        another_user = create_random_default_user("another_user")
        url = "/api/user/mark_probable_spammer/"
        data = {"authorId": another_user.author_profile.id}
        self.client.force_authenticate(user=regular_user)
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 403)

    def test_mark_probable_spammer_missing_author_id(self):
        url = "/api/user/mark_probable_spammer/"
        data = {}
        self.client.force_authenticate(user=self.moderator)
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 400)

    def test_mark_probable_spammer_user_not_found(self):
        url = "/api/user/mark_probable_spammer/"
        data = {"authorId": -1}
        self.client.force_authenticate(user=self.moderator)
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 404)
