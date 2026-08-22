from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from feed.models import FeedEntry
from researchhub_document.helpers import create_post
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.services.unified_document_feed_visibility_service import (
    UnifiedDocumentFeedVisibilityService,
)
from user.tests.helpers import create_random_default_user


class UnifiedDocumentFeedVisibilityServiceTests(TestCase):
    def setUp(self):
        self.activity_feed_cache_warmer = Mock()
        self.service = UnifiedDocumentFeedVisibilityService(
            activity_feed_cache_warmer=self.activity_feed_cache_warmer
        )
        self.author = create_random_default_user("feed-vis-author")
        self.post = create_post(created_by=self.author, title="Visible post")
        self.unified_document = self.post.unified_document

    def test_exclude_document_from_feed(self):
        # Act
        with self.captureOnCommitCallbacks(execute=True):
            result = self.service.exclude_from_feed(self.unified_document.id)

        # Assert
        self.unified_document.document_filter.refresh_from_db()
        self.assertTrue(result.document_filter.is_excluded_in_feed)
        self.assertTrue(self.unified_document.document_filter.is_excluded_in_feed)
        self.activity_feed_cache_warmer.assert_called_once()

    def test_include_document_in_feed(self):
        # Arrange
        with self.captureOnCommitCallbacks(execute=True):
            self.service.exclude_from_feed(self.unified_document.id)
        self.activity_feed_cache_warmer.reset_mock()

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            result = self.service.include_in_feed(self.unified_document.id)

        # Assert
        self.assertFalse(result.document_filter.is_excluded_in_feed)
        self.activity_feed_cache_warmer.assert_called_once()

    def test_exclude_and_include_are_idempotent(self):
        # Act
        with self.captureOnCommitCallbacks(execute=True):
            first = self.service.exclude_from_feed(self.unified_document.id)
            second = self.service.exclude_from_feed(self.unified_document.id)
            included_once = self.service.include_in_feed(self.unified_document.id)
            included_twice = self.service.include_in_feed(self.unified_document.id)

        # Assert
        self.assertTrue(first.document_filter.is_excluded_in_feed)
        self.assertTrue(second.document_filter.is_excluded_in_feed)
        self.assertFalse(included_once.document_filter.is_excluded_in_feed)
        self.assertFalse(included_twice.document_filter.is_excluded_in_feed)
        self.assertEqual(self.activity_feed_cache_warmer.call_count, 2)

    def test_missing_document_raises_does_not_exist(self):
        # Act / Assert
        with self.assertRaises(ResearchhubUnifiedDocument.DoesNotExist):
            self.service.exclude_from_feed(999999999)
        self.activity_feed_cache_warmer.assert_not_called()

    def test_creates_document_filter_when_missing(self):
        # Arrange: legacy rows can have a null document_filter
        ResearchhubUnifiedDocument.objects.filter(pk=self.unified_document.pk).update(
            document_filter=None
        )
        self.unified_document.refresh_from_db()
        self.assertIsNone(self.unified_document.document_filter_id)

        # Act
        result = self.service.exclude_from_feed(self.unified_document.id)

        # Assert
        result.refresh_from_db()
        self.assertIsNotNone(result.document_filter_id)
        self.assertTrue(result.document_filter.is_excluded_in_feed)

    def test_hiding_does_not_delete_feed_entries(self):
        # Arrange
        entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

        # Act
        self.service.exclude_from_feed(self.unified_document.id)

        # Assert
        self.assertTrue(FeedEntry.objects.filter(pk=entry.pk).exists())

    @patch("feed.views.activity_feed_view.ActivityFeedViewSet.warm_public_cache")
    @patch("feed.tasks.warm_activity_feed_cache.delay")
    def test_queues_celery_cache_warm_after_commit(self, mock_delay, mock_warm):
        # Arrange
        service = UnifiedDocumentFeedVisibilityService()

        # Act
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            service.exclude_from_feed(self.unified_document.id)

        # Assert: the request does not rebuild cache pages inline
        mock_delay.assert_not_called()
        mock_warm.assert_not_called()
        self.assertEqual(len(callbacks), 1)

        # Act: after the hide is committed, enqueue the existing Celery task
        callbacks[0]()

        # Assert
        mock_delay.assert_called_once_with()
        mock_warm.assert_not_called()
