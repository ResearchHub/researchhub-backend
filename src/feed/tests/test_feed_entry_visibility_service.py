from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from feed.models import FeedEntry, HiddenFeedEntry
from feed.services.feed_entry_visibility_service import FeedEntryVisibilityService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.tests.helpers import create_random_default_user


class FeedEntryVisibilityServiceTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.activity_feed_cache_warmer = Mock()
        self.on_commit_patcher = patch(
            "feed.services.feed_entry_visibility_service.transaction.on_commit",
            side_effect=lambda func, **kwargs: func(),
        )
        self.on_commit_patcher.start()
        self.addCleanup(self.on_commit_patcher.stop)
        self.service = FeedEntryVisibilityService(
            activity_feed_cache_warmer=self.activity_feed_cache_warmer
        )
        self.moderator = create_random_default_user(
            "feed-entry-vis-mod", moderator=True
        )
        self.post = create_post(
            created_by=self.moderator, title="Feed entry visibility"
        )
        self.feed_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            unified_document=self.post.unified_document,
            user=self.moderator,
            content={},
            metrics={},
        )

    def tearDown(self):
        cache.clear()

    def test_exclude_creates_hidden_row(self):
        # Act
        result = self.service.exclude_from_feed(self.feed_entry.id, self.moderator)

        # Assert
        self.assertEqual(result.id, self.feed_entry.id)
        self.assertTrue(
            HiddenFeedEntry.objects.filter(feed_entry=self.feed_entry).exists()
        )
        self.activity_feed_cache_warmer.assert_called_once()

    def test_include_removes_hidden_row(self):
        # Arrange
        self.service.exclude_from_feed(self.feed_entry.id, self.moderator)
        self.activity_feed_cache_warmer.reset_mock()

        # Act
        result = self.service.include_in_feed(self.feed_entry.id)

        # Assert
        self.assertEqual(result.id, self.feed_entry.id)
        self.assertFalse(
            HiddenFeedEntry.objects.filter(feed_entry=self.feed_entry).exists()
        )
        self.activity_feed_cache_warmer.assert_called_once()

    def test_exclude_is_idempotent(self):
        # Act
        first = self.service.exclude_from_feed(self.feed_entry.id, self.moderator)
        self.activity_feed_cache_warmer.reset_mock()
        second = self.service.exclude_from_feed(self.feed_entry.id, self.moderator)

        # Assert
        self.assertEqual(first.id, second.id)
        self.activity_feed_cache_warmer.assert_not_called()

    @patch("feed.tasks.warm_activity_feed_cache.delay")
    def test_default_cache_warmer_uses_celery(self, mock_delay):
        # Arrange
        service = FeedEntryVisibilityService()

        # Act
        service.exclude_from_feed(self.feed_entry.id, self.moderator)

        # Assert
        mock_delay.assert_called_once()

    def test_list_excluded_from_feed_returns_hidden_entries(self):
        # Arrange
        self.service.exclude_from_feed(self.feed_entry.id, self.moderator)

        # Act
        ids = list(self.service.list_excluded_from_feed().values_list("id", flat=True))

        # Assert
        self.assertEqual(ids, [self.feed_entry.id])
