from datetime import datetime

from django.test import TestCase

from analytics.models import UserInteractions
from analytics.tasks import process_amplitude_event
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class ProcessAmplitudeEventTaskTestCase(TestCase):
    """Test cases for the process_amplitude_event Celery task."""

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
