from django.test import TestCase

from analytics.services.event_processor import EventProcessor
from user.tests.helpers import create_random_default_user


class EventProcessorTestCase(TestCase):
    """
    Test cases for the EventProcessor service.
    """

    def setUp(self):
        self.processor = EventProcessor()
        self.user = create_random_default_user("test_user")

    def test_should_process_event_always_returns_true(self):
        """Test that should_process_event always returns True."""
        event = {
            "event_type": "vote_action",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.unified_document_id": "doc_123",
                "related_work.content_type": "paper",
            },
        }
        self.assertTrue(self.processor.should_process_event(event))

    def test_process_event_logs_correctly(self):
        """Test that process_event logs the event correctly."""
        event = {
            "event_type": "vote_action",
            "event_properties": {
                "user_id": str(self.user.id),
            },
        }

        # Should not raise an exception
        self.processor.process_event(event)
