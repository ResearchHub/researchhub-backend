from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import Author, User, UserVerification
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
    create_random_default_user,
    create_user,
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
        author_profile = self.user_with_published_works.author_profile

        # Act
        url = f"/api/author/{author_profile.id}/publications/"
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
        author_profile = self.user_with_published_works.author_profile

        # Act
        url = f"/api/author/{author_profile.id}/publications/"
        resp = self.client.get(url)

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)
        cache_key = f"author-{author_profile.id}-publications"
        self.assertEqual(cache.get(cache_key)[0].paper, paper)

    def test_get_publications_reads_from_cache(self):
        # Arrange
        self.client.force_authenticate(self.user_with_published_works)

        document = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        Paper.objects.create(title="title1", unified_document=document)

        author_profile = self.user_with_published_works.author_profile
        cache_key = f"author-{author_profile.id}-publications"
        cache.set(cache_key, [document])

        # Act
        url = f"/api/author/{author_profile.id}/publications/"
        resp = self.client.get(url)

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)
        self.assertEqual(
            resp.json()["results"][0]["documents"]["id"], document.paper.id
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
        author_profile = self.user_with_published_works.author_profile

        # Act
        url = f"/api/author/{author_profile.id}/publications/"
        resp = self.client.delete(url, {"paper_ids": [paper1.id, paper2.id]})

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)
        self.assertFalse(
            Authorship.objects.filter(
                author=author_profile,
                paper__id__in=[paper1.id, paper2.id],
            ).exists()
        )

    def test_delete_publications_paper_not_found(self):
        # Arrange
        self.client.force_authenticate(self.user_with_published_works)
        author_profile = self.user_with_published_works.author_profile

        # Act
        url = f"/api/author/{author_profile.id}/publications/"
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

        author_profile = self.user_with_published_works.author_profile
        paper = Paper.objects.create(
            title="title1",
        )
        Authorship.objects.create(author=author_profile, paper=paper)

        # Act
        url = f"/api/author/{author_profile.id}/publications/"
        resp = self.client.delete(url, {"paper_ids": [paper.id]})

        # Assert
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)
        self.assertTrue(
            Authorship.objects.filter(author=author_profile, paper=paper).exists()
        )


class UserViewsTests(APITestCase):
    def test_delete_soft_deletes_user_and_author_profile(self):
        # Arrange
        user = create_random_authenticated_user("soft_delete_user")
        author_id = user.author_profile.id
        url = f"/api/user/{user.id}/"
        self.client.force_authenticate(user)

        # Act
        response = self.client.delete(url)

        # Assert
        self.assertEqual(response.status_code, 204)
        deleted_user = User.all_objects.get(pk=user.pk)
        deleted_author = Author.all_objects.get(pk=author_id)
        self.assertFalse(deleted_user.is_active)
        self.assertTrue(deleted_user.is_removed)
        self.assertFalse(deleted_user.is_public)
        self.assertIsNotNone(deleted_user.is_removed_date)
        self.assertTrue(deleted_author.is_removed)
        self.assertFalse(deleted_author.is_public)
        self.assertIsNotNone(deleted_author.is_removed_date)
        self.assertEqual(deleted_author.user_id, deleted_user.id)

    def test_soft_deleted_user_profile_is_not_retrievable(self):
        # Arrange
        user = create_random_authenticated_user("hidden_soft_delete_user")
        url = f"/api/user/{user.id}/"
        self.client.force_authenticate(user)
        self.client.delete(url)

        # Act
        response = self.client.get(url)

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_set_staking_opted_in_preserves_existing_opt_in_date(self):
        user = create_random_authenticated_user("staking_opt_in")
        original_opt_in_date = timezone.now() - timedelta(days=2)
        user.is_staking_opted_in = True
        user.staking_opted_in_date = original_opt_in_date
        user.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])

        url = "/api/user/set_staking_opted_in/"
        self.client.force_authenticate(user)
        response = self.client.patch(
            url,
            {"is_staking_opted_in": True},
        )

        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        self.assertTrue(user.is_staking_opted_in)
        self.assertEqual(user.staking_opted_in_date, original_opt_in_date)


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
        """
        Test that only moderators or hub editors can mark users as probable spammers
        """
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
