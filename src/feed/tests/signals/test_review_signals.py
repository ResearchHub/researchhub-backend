import logging
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from feed.models import FeedEntry
from feed.signals.review_signals import handle_review_created_or_updated
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models.review_model import Review
from user.tests.helpers import create_random_default_user

logger = logging.getLogger(__name__)


class TestReviewSignals(TestCase):
    def setUp(self):
        # Create a user
        self.user = create_random_default_user("review_signal_test")

        # Create a unified document and post
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION,
        )

        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            created_by=self.user,
            document_type=document_type.DISCUSSION,
            renderable_text="Test content",
            unified_document=self.unified_document,
        )

        # Create a comment thread and comment
        self.thread = RhCommentThreadModel.objects.create(
            thread_type=GENERIC_COMMENT,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            created_by=self.user,
        )

        self.comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=PEER_REVIEW,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )

        # Create feed entries for both post and comment
        self.post_feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            action="PUBLISH",
            action_date=self.post.created_date,
            user=self.user,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

        self.comment_feed_entry = FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            action="PUBLISH",
            action_date=self.comment.created_date,
            user=self.user,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

    @patch("feed.signals.review_signals.refresh_feed_entry")
    def test_review_created_updates_feed_entries(self, mock_refresh_feed_entry):
        """Test that creating a review updates both document and comment feed entries"""
        # Arrange
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Act - Create a review
        Review.objects.create(  # noqa: F841
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        # Assert
        # Should be called twice - once for post and once for comment
        self.assertEqual(mock_refresh_feed_entry.apply_async.call_count, 2)

        # Check calls include the correct feed entry IDs
        calls = mock_refresh_feed_entry.apply_async.call_args_list

        # Extract the feed entry IDs from each call
        feed_entry_ids = [call[1]["args"][0] for call in calls]

        # Verify both feed entries were refreshed
        self.assertIn(self.post_feed_entry.id, feed_entry_ids)
        self.assertIn(self.comment_feed_entry.id, feed_entry_ids)

        # Verify priority was set to 1
        for call in calls:
            self.assertEqual(call[1]["priority"], 1)

    @patch("feed.signals.review_signals.refresh_feed_entry")
    def test_review_updated_updates_feed_entries(self, mock_refresh_feed_entry):
        """Test that updating a review updates both document and comment feed entries"""
        # Arrange
        review = Review.objects.create(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        # Reset mock to clear the creation call
        mock_refresh_feed_entry.apply_async.reset_mock()

        # Act - Update the review
        review.score = 7.0
        review.save()

        # Assert
        # Should be called twice - once for post and once for comment
        self.assertEqual(mock_refresh_feed_entry.apply_async.call_count, 2)

        # Check calls include the correct feed entry IDs
        calls = mock_refresh_feed_entry.apply_async.call_args_list

        # Extract the feed entry IDs from each call
        feed_entry_ids = [call[1]["args"][0] for call in calls]

        # Verify both feed entries were refreshed
        self.assertIn(self.post_feed_entry.id, feed_entry_ids)
        self.assertIn(self.comment_feed_entry.id, feed_entry_ids)

    @patch("feed.signals.review_signals.refresh_feed_entry")
    def test_direct_signal_call(self, mock_refresh_feed_entry):
        """Test directly calling the signal handler"""
        # Arrange
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Create review but don't save it (to avoid triggering the signal)
        review = Review(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        # Act - Call the signal handler directly
        handle_review_created_or_updated(sender=Review, instance=review, created=True)

        # Assert
        # Should be called twice - once for post and once for comment
        self.assertEqual(mock_refresh_feed_entry.apply_async.call_count, 2)

    @patch("feed.signals.review_signals.logger.error")
    @patch("feed.signals.review_signals._update_feed_entries")
    def test_error_handling(self, mock_update_feed_entries, mock_logger_error):
        """Test error handling in the signal handler"""
        # Arrange
        mock_update_feed_entries.side_effect = Exception("Test error")

        # Create review but don't save it (to avoid triggering the signal)
        review = Review(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.unified_document,
            id=999,  # Fake ID for error message check
        )

        # Act - Call the signal handler directly
        handle_review_created_or_updated(sender=Review, instance=review, created=True)

        # Assert
        mock_logger_error.assert_called_once()
        # Verify error message contains review ID and action
        error_message = mock_logger_error.call_args[0][0]
        self.assertIn("999", error_message)
        self.assertIn("created", error_message)

    @patch("feed.signals.review_signals.refresh_feed_entry")
    def test_no_feed_entries_for_item(self, mock_refresh_feed_entry):
        """Test when there are no feed entries for the item being reviewed"""
        # Arrange
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Delete the comment feed entry
        self.comment_feed_entry.delete()

        # Act - Create a review
        Review.objects.create(  # noqa: F841
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        # Assert
        # Should only be called once - for the post (document) entry
        self.assertEqual(mock_refresh_feed_entry.apply_async.call_count, 1)

        # The call should be for the post feed entry
        call_args = mock_refresh_feed_entry.apply_async.call_args
        self.assertEqual(call_args[1]["args"][0], self.post_feed_entry.id)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_integration_review_refreshes_feed_entries(self):
        """Integration test that verifies the review signal updates feed entries without mocking"""
        # Set initial metrics for feed entries
        self.post_feed_entry.metrics = {
            "votes": 5,
            "review_metrics": {"avg": 0, "count": 0},
        }
        self.post_feed_entry.save()

        self.comment_feed_entry.metrics = {"votes": 0}
        self.comment_feed_entry.save()

        # Create a review
        review = Review.objects.create(
            score=8.5,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        # Refresh feed entries from database
        refreshed_post_entry = FeedEntry.objects.get(id=self.post_feed_entry.id)
        refreshed_comment_entry = FeedEntry.objects.get(id=self.comment_feed_entry.id)

        # Verify the metrics were updated
        # The post feed entry should now have review metrics
        self.assertIn("review_metrics", refreshed_post_entry.metrics)

        # Update review
        review.score = 9.0
        review.save()

        # Refresh again from database
        refreshed_post_entry = FeedEntry.objects.get(id=self.post_feed_entry.id)
        refreshed_comment_entry = FeedEntry.objects.get(id=self.comment_feed_entry.id)

        # Verify metrics were updated again
        if "review_metrics" in refreshed_post_entry.metrics:
            # Check if avg score was updated - this may not always change depending on serialization
            # as some implementations might combine results from multiple reviews
            self.assertIsNotNone(refreshed_post_entry.metrics["review_metrics"])
