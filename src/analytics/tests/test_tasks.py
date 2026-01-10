from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from analytics.models import UserInteractions
from analytics.tasks import process_amplitude_event
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class ProcessAmplitudeEventTaskTestCase(TestCase):
    """Test cases for the process_amplitude_event Celery task."""

    @patch("analytics.services.event_processor.EventProcessor")
    def test_task_calls_event_processor(self, mock_processor_class):
        """Test that the task instantiates and calls EventProcessor."""
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor

        event = {"event_type": "test", "event_properties": {}}

        process_amplitude_event(event)

        mock_processor_class.assert_called_once()
        mock_processor.process_event.assert_called_once_with(event)

    def test_task_processes_event_end_to_end(self):
        """Integration test: task processes event and creates database record."""
        user = create_random_default_user("test_user")
        post = create_post(created_by=user)

        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(user.id),
                "related_work": {
                    "unified_document_id": str(post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(post.id),
                },
            },
            "time_": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()

        # Call task synchronously (without .delay())
        process_amplitude_event(event)

        # Verify database record was created
        final_count = UserInteractions.objects.count()
        self.assertEqual(final_count, initial_count + 1)

        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, user)
        self.assertEqual(interaction.event, "FEED_ITEM_CLICK")
        self.assertEqual(interaction.unified_document, post.unified_document)
