from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.serializers import serialize_feed_metrics
from hub.models import Hub
from paper.related_models.paper_model import Paper
from user.models import User


class PaperSignalsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.paper = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
        )
        self.hub = Hub.objects.create(name="Test Hub")
        self.paper.unified_document.hubs.add(self.hub)

        self.content_type = ContentType.objects.get_for_model(Paper)

        # Create a feed entry for the paper
        self.feed_entry = FeedEntry.objects.create(
            content_type=self.content_type,
            object_id=self.paper.id,
            user=self.user,
            action=FeedEntry.PUBLISH,
            action_date=self.paper.created_date,
            unified_document=self.paper.unified_document,
        )

    @patch("feed.signals.paper_signals.update_feed_metrics")
    def test_handle_paper_external_metadata_updated(self, mock_update_feed_metrics):
        """
        Test that feed metrics are updated when paper external_metadata is updated
        with metrics data.
        """
        # Arrange
        mock_update_feed_metrics.apply_async = MagicMock()

        # Add metrics data to external_metadata
        self.paper.external_metadata = {
            "metrics": {
                "score": 42.5,
                "facebook_count": 15,
                "twitter_count": 230,
                "bluesky_count": 8,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        }

        # Act - save with update_fields to trigger the signal
        self.paper.save(update_fields=["external_metadata"])

        # Assert
        expected_metrics = serialize_feed_metrics(self.paper, self.content_type)
        mock_update_feed_metrics.apply_async.assert_called_once_with(
            args=(
                self.paper.id,
                self.content_type.id,
                expected_metrics,
            ),
            priority=3,
        )

    @patch("feed.signals.paper_signals.update_feed_metrics")
    def test_signal_not_triggered_when_other_fields_updated(
        self, mock_update_feed_metrics
    ):
        """
        Test that the signal is not triggered when other fields are updated.
        """
        # Arrange
        mock_update_feed_metrics.apply_async = MagicMock()

        # Act - update a different field
        self.paper.title = "Updated Title"
        self.paper.save(update_fields=["title"])

        # Assert
        mock_update_feed_metrics.apply_async.assert_not_called()

    @patch("feed.signals.paper_signals.update_feed_metrics")
    def test_signal_not_triggered_when_no_metrics_in_external_metadata(
        self, mock_update_feed_metrics
    ):
        """
        Test that the signal is not triggered when external_metadata
        doesn't contain metrics.
        """
        # Arrange
        mock_update_feed_metrics.apply_async = MagicMock()

        # Act - update external_metadata without metrics
        self.paper.external_metadata = {"other_data": "value"}
        self.paper.save(update_fields=["external_metadata"])

        # Assert
        mock_update_feed_metrics.apply_async.assert_not_called()

    @patch("feed.signals.paper_signals.update_feed_metrics")
    def test_signal_not_triggered_when_external_metadata_is_none(
        self, mock_update_feed_metrics
    ):
        """
        Test that the signal is not triggered when external_metadata is None.
        """
        # Arrange
        mock_update_feed_metrics.apply_async = MagicMock()

        # Act - set external_metadata to None
        self.paper.external_metadata = None
        self.paper.save(update_fields=["external_metadata"])

        # Assert
        mock_update_feed_metrics.apply_async.assert_not_called()

    @patch("feed.signals.paper_signals.update_feed_metrics")
    def test_signal_handles_multiple_metrics_updates(self, mock_update_feed_metrics):
        """
        Test that the signal properly handles multiple updates to external_metadata.
        """
        # Arrange
        mock_update_feed_metrics.apply_async = MagicMock()

        # Act - First update
        self.paper.external_metadata = {
            "metrics": {
                "score": 10.0,
                "facebook_count": 5,
                "twitter_count": 50,
                "bluesky_count": 2,
            }
        }
        self.paper.save(update_fields=["external_metadata"])

        # Second update
        self.paper.external_metadata = {
            "metrics": {
                "score": 20.0,
                "facebook_count": 10,
                "twitter_count": 100,
                "bluesky_count": 5,
            }
        }
        self.paper.save(update_fields=["external_metadata"])

        # Assert - should be called twice
        self.assertEqual(mock_update_feed_metrics.apply_async.call_count, 2)

    @patch("feed.signals.paper_signals.update_feed_metrics")
    @patch("feed.signals.paper_signals.logger")
    def test_signal_logs_error_on_exception(
        self, mock_logger, mock_update_feed_metrics
    ):
        """
        Test that errors are properly logged when the signal handler fails.
        """
        # Arrange
        mock_update_feed_metrics.apply_async.side_effect = Exception("Test error")

        # Act
        self.paper.external_metadata = {
            "metrics": {
                "score": 42.5,
                "facebook_count": 15,
            }
        }
        self.paper.save(update_fields=["external_metadata"])

        # Assert - error should be logged
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        self.assertIn("Failed to update feed metrics", error_message)
        self.assertIn(str(self.paper.id), error_message)

    @patch("feed.signals.paper_signals.update_feed_metrics")
    def test_signal_includes_x_metrics_in_serialized_data(
        self, mock_update_feed_metrics
    ):
        """
        Test end-to-end: saving external_metadata with X data triggers
        update_feed_metrics with X metrics included in the serialized data.
        """
        # Arrange
        mock_update_feed_metrics.apply_async = MagicMock()

        x_metrics = {
            "post_count": 3,
            "total_likes": 25,
            "total_quotes": 2,
            "total_replies": 1,
            "total_reposts": 10,
            "total_impressions": 1000,
        }

        self.paper.external_metadata = {"metrics": {"x": x_metrics}}

        # Act - save with update_fields to trigger the signal
        self.paper.save(update_fields=["external_metadata"])

        # Assert - signal was called
        mock_update_feed_metrics.apply_async.assert_called_once()

        # Get the metrics that were passed to the signal
        call_args = mock_update_feed_metrics.apply_async.call_args
        passed_metrics = call_args[1]["args"][2]

        # Verify X metrics are included
        self.assertIn("external", passed_metrics)
        self.assertIn("x", passed_metrics["external"])
        self.assertEqual(passed_metrics["external"]["x"]["total_likes"], 25)
        self.assertEqual(passed_metrics["external"]["x"]["total_impressions"], 1000)
