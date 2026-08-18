from unittest.mock import patch

from django.core.cache import cache
from rest_framework.test import APITestCase

from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class UnifiedDocumentFeedVisibilityViewTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.warm_patcher = patch(
            "researchhub_document.services.unified_document_feed_visibility_service."
            "UnifiedDocumentFeedVisibilityService._queue_activity_feed_cache_warm"
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

    def test_missing_document_returns_404(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        missing_url = "/api/researchhub_unified_document/999999999/exclude_from_feed/"

        # Act
        response = self.client.post(missing_url)

        # Assert
        self.assertEqual(response.status_code, 404)
