from rest_framework.test import APITestCase

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from user.tests.helpers import create_user


class AuthorApiTests(APITestCase):
    def setUp(self):
        self.user_with_published_works = create_user(
            email="random@researchhub.com",
            first_name="Yang",
            last_name="Wang",
        )

        paper1 = Paper.objects.create(
            title="title1",
            citations=10,
        )
        paper2 = Paper.objects.create(
            title="title2",
            citations=20,
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper1
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper2
        )

    def test_get_author_summary_stats(self):
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/summary_stats/"
        response = self.client.get(url, {})
        self.assertIn("summary_stats", response.data)

    def test_get_achievements(self):
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/achievements/"
        response = self.client.get(url, {})
        self.assertIn("achievements", response.data)

    def test_get_profile(self):
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/profile/"
        response = self.client.get(url, {})
        self.assertIn("id", response.data)

    def test_minimal_overview(self):
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/minimal_overview/"
        response = self.client.get(url, {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.data)
        self.assertIn("first_name", response.data)
        self.assertIn("last_name", response.data)
        # Check that the editor_of field is not included
        self.assertNotIn("editor_of", response.data)
