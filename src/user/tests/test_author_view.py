from rest_framework.test import APITestCase

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from user.models import Author, User
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
        author_profile = self.user_with_published_works.author_profile
        url = f"/api/author/{author_profile.id}/summary_stats/"
        response = self.client.get(url, {})
        self.assertIn("summary_stats", response.data)

    def test_get_achievements(self):
        author_profile = self.user_with_published_works.author_profile
        url = f"/api/author/{author_profile.id}/achievements/"
        response = self.client.get(url, {})
        self.assertIn("achievements", response.data)

    def test_minimal_overview(self):
        author_profile = self.user_with_published_works.author_profile
        url = f"/api/author/{author_profile.id}/minimal_overview/"
        response = self.client.get(url, {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.data)
        self.assertIn("first_name", response.data)
        self.assertIn("last_name", response.data)
        # Check that the editor_of field is not included
        self.assertNotIn("editor_of", response.data)

    def test_delete_soft_deletes_author_and_linked_user(self):
        # Arrange
        user = self.user_with_published_works
        author = user.author_profile
        url = f"/api/author/{author.id}/"
        self.client.force_authenticate(user)

        # Act
        response = self.client.delete(url)

        # Assert
        self.assertEqual(response.status_code, 204)
        deleted_author = Author.all_objects.get(pk=author.pk)
        deleted_user = User.all_objects.get(pk=user.pk)
        self.assertTrue(deleted_author.is_removed)
        self.assertFalse(deleted_author.is_public)
        self.assertIsNotNone(deleted_author.is_removed_date)
        self.assertTrue(deleted_user.is_removed)
        self.assertFalse(deleted_user.is_active)
        self.assertEqual(Authorship.objects.filter(author=author).count(), 2)

    def test_soft_deleted_author_profile_is_not_retrievable(self):
        # Arrange
        user = self.user_with_published_works
        author = user.author_profile
        url = f"/api/author/{author.id}/"
        self.client.force_authenticate(user)
        self.client.delete(url)

        # Act
        response = self.client.get(url)

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_moderator_can_soft_delete_unclaimed_author(self):
        # Arrange
        moderator = create_user(
            email="moderator@researchhub.com",
            moderator=True,
        )
        author = Author.objects.create(first_name="Unclaimed", last_name="Author")
        url = f"/api/author/{author.id}/"
        self.client.force_authenticate(moderator)

        # Act
        response = self.client.delete(url)

        # Assert
        self.assertEqual(response.status_code, 204)
        author.refresh_from_db()
        self.assertTrue(author.is_removed)
        self.assertFalse(author.is_public)
        self.assertIsNotNone(author.is_removed_date)
