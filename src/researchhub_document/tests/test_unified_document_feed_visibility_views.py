from unittest.mock import patch

from django.core.cache import cache
from rest_framework.test import APITestCase

from researchhub_document.helpers import create_post
from user.tests.helpers import create_hub_editor, create_random_default_user


class UnifiedDocumentFeedVisibilityViewTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.warm_patcher = patch(
            "researchhub_document.services.unified_document_feed_visibility_service."
            "UnifiedDocumentFeedVisibilityService._warm_activity_feed_cache"
        )
        self.mock_warm = self.warm_patcher.start()
        self.addCleanup(self.warm_patcher.stop)

        self.moderator = create_random_default_user("feed-vis-view-mod", moderator=True)
        self.author = create_random_default_user("feed-vis-view-author")
        self.post = create_post(created_by=self.author, title="Feed visibility post")
        self.unified_document = self.post.unified_document
        self.exclude_url = (
            f"/api/researchhub_unified_document/{self.unified_document.id}"
            "/exclude_from_feed/"
        )
        self.include_url = (
            f"/api/researchhub_unified_document/{self.unified_document.id}"
            "/include_in_feed/"
        )
        self.list_url = "/api/researchhub_unified_document/excluded_from_feed/"

    def tearDown(self):
        cache.clear()

    def test_moderator_exclude_returns_compact_state(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(self.exclude_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"id": self.unified_document.id, "is_excluded_in_feed": True},
        )
        self.unified_document.document_filter.refresh_from_db()
        self.assertTrue(self.unified_document.document_filter.is_excluded_in_feed)

    def test_moderator_include_returns_compact_state(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        self.client.post(self.exclude_url)

        # Act
        response = self.client.post(self.include_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"id": self.unified_document.id, "is_excluded_in_feed": False},
        )

    def test_exclude_and_include_are_idempotent(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act / Assert
        first = self.client.post(self.exclude_url)
        second = self.client.post(self.exclude_url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data, second.data)
        self.assertTrue(second.data["is_excluded_in_feed"])

        included_once = self.client.post(self.include_url)
        included_twice = self.client.post(self.include_url)
        self.assertEqual(included_once.status_code, 200)
        self.assertEqual(included_twice.status_code, 200)
        self.assertEqual(included_once.data, included_twice.data)
        self.assertFalse(included_twice.data["is_excluded_in_feed"])

    def test_anonymous_user_is_unauthorized(self):
        # Act
        self.client.force_authenticate(user=None)
        response = self.client.post(self.exclude_url)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_non_moderator_is_forbidden(self):
        # Arrange
        editor, _ = create_hub_editor("feed-vis-view-editor", "feed-vis-view-hub")

        # Act / Assert
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.post(self.exclude_url).status_code, 403)

        self.client.force_authenticate(editor)
        self.assertEqual(self.client.post(self.include_url).status_code, 403)

        self.unified_document.document_filter.refresh_from_db()
        self.assertFalse(self.unified_document.document_filter.is_excluded_in_feed)

    def test_missing_document_returns_404(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        missing_url = "/api/researchhub_unified_document/999999999/exclude_from_feed/"

        # Act
        response = self.client.post(missing_url)

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_non_numeric_id_returns_404(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            "/api/researchhub_unified_document/abc/exclude_from_feed/"
        )

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_exclude_warms_activity_feed_cache_once(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        self.client.post(self.exclude_url)
        self.client.post(self.exclude_url)

        # Assert: a no-op second hide does not rebuild the 20 cached pages
        self.assertEqual(self.mock_warm.call_count, 1)

    def test_list_returns_work_payload_with_remapped_ids(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        self.client.post(self.exclude_url)

        # Act
        response = self.client.get(self.list_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], self.unified_document.id)
        self.assertEqual(row["document_id"], self.post.id)
        self.assertEqual(row["document_type"], self.post.document_type)
        self.assertEqual(row["title"], self.post.title)
        self.assertEqual(row["slug"], self.post.slug)
        self.assertIsNone(row["image_url"])
        self.assertIn("created_by", row)
        self.assertEqual(row["created_by"]["id"], self.author.author_profile.id)
        self.assertNotIn("unified_document_id", row)

    def test_list_omits_document_after_restore(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        self.client.post(self.exclude_url)

        # Act
        self.client.post(self.include_url)
        response = self.client.get(self.list_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_list_filters_by_title_query(self):
        # Arrange
        matching = create_post(created_by=self.author, title="UniqueAlpha hidden")
        other = create_post(created_by=self.author, title="Beta hidden")
        self.client.force_authenticate(self.moderator)
        self.client.post(
            f"/api/researchhub_unified_document/{matching.unified_document.id}"
            "/exclude_from_feed/"
        )
        self.client.post(
            f"/api/researchhub_unified_document/{other.unified_document.id}"
            "/exclude_from_feed/"
        )

        # Act
        response = self.client.get(self.list_url, {"query": "uniquealpha"})

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["id"], matching.unified_document.id
        )

    def test_list_paginates(self):
        # Arrange
        first = create_post(created_by=self.author, title="First hidden")
        second = create_post(created_by=self.author, title="Second hidden")
        self.client.force_authenticate(self.moderator)
        self.client.post(
            f"/api/researchhub_unified_document/{first.unified_document.id}"
            "/exclude_from_feed/"
        )
        self.client.post(
            f"/api/researchhub_unified_document/{second.unified_document.id}"
            "/exclude_from_feed/"
        )

        # Act
        response = self.client.get(self.list_url, {"page": 1, "page_size": 1})

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["next"])
        self.assertEqual(response.data["results"][0]["id"], second.unified_document.id)

    def test_list_anonymous_user_is_unauthorized(self):
        # Act
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_list_non_moderator_is_forbidden(self):
        # Arrange
        editor, _ = create_hub_editor("feed-vis-list-editor", "feed-vis-list-hub")

        # Act / Assert
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

        self.client.force_authenticate(editor)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
