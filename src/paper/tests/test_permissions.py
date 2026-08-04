import random

from rest_framework import status
from rest_framework.test import APITestCase

from paper.models import Paper, PaperVersion
from user.models import User
from user.tests.helpers import create_random_authenticated_user

from .helpers import create_paper


class PaperPermissionsIntegrationTests(APITestCase):
    def setUp(self):
        self.random_generator = random.Random("paper")
        self.base_url = "/api/paper/"
        self.paper = create_paper()
        self.flag_reason = "Inappropriate"

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

    def test_prevents_creating_papers(self) -> None:
        """The paper API does not expose direct paper creation routes."""
        # Arrange
        user = self.create_user_with_reputation(1)
        paper_count = Paper.objects.count()
        retired_creation_urls = [
            self.base_url,
            f"{self.base_url}create_researchhub_paper/",
            f"{self.base_url}publish_to_researchhub_journal/",
            f"{self.base_url}upload/",
        ]
        self.client.force_authenticate(user)

        # Act
        responses = {
            url: self.client.post(url, {"title": "Disallowed paper"}, format="json")
            for url in retired_creation_urls
        }

        # Assert
        for url, response in responses.items():
            with self.subTest(url=url):
                self.assertIn(
                    response.status_code,
                    (status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED),
                )
        self.assertEqual(Paper.objects.count(), paper_count)

    def test_prevents_updating_legacy_journal_papers(self) -> None:
        """Legacy journal papers cannot be updated through the paper API."""
        # Arrange
        paper = self.create_legacy_journal_paper()
        user = self.create_user_with_reputation(1)
        self.client.force_authenticate(user)

        # Act
        response = self.client.patch(
            f"{self.base_url}{paper.id}/",
            {"title": "Updated legacy paper"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        paper.refresh_from_db()
        self.assertNotEqual(paper.title, "Updated legacy paper")

    def test_prevents_deleting_papers(self) -> None:
        """The paper API does not expose direct paper deletion."""
        # Arrange
        user = self.create_user_with_reputation(1)
        self.client.force_authenticate(user)

        # Act
        response = self.client.delete(f"{self.base_url}{self.paper.id}/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Paper.objects.filter(id=self.paper.id).exists())

    def test_prevents_moderating_legacy_journal_papers(self) -> None:
        """Legacy journal papers cannot be moderated or censored."""
        # Arrange
        moderator = self.create_user_with_reputation(1)
        moderator.moderator = True
        moderator.save(update_fields=["moderator"])
        paper = self.create_legacy_journal_paper(uploaded_by=moderator)
        self.client.force_authenticate(moderator)

        # Act
        responses = [
            self.client.post(f"{self.base_url}{paper.id}/approve/"),
            self.client.post(f"{self.base_url}{paper.id}/decline/"),
            self.client.delete(f"{self.base_url}{paper.id}/censor/"),
        ]

        # Assert
        for response in responses:
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        paper.refresh_from_db()
        self.assertFalse(paper.is_removed)

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

    def create_legacy_journal_paper(self, uploaded_by: User | None = None) -> Paper:
        """Create a paper that represents an existing legacy journal entry."""
        paper = create_paper(uploaded_by=uploaded_by)
        PaperVersion.objects.create(
            paper=paper,
            version=1,
            original_paper=paper,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PUBLISHED,
        )
        return paper

    def get_patch_response(self, user, paper):
        if paper is None:
            paper = self.paper
        url = self.base_url + f"{paper.id}/"
        data = {"title": "Patched Paper Title"}
        self.client.force_authenticate(user)
        return self.client.patch(url, data, format="multipart")

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
