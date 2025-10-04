from datetime import datetime
from unittest.mock import MagicMock, patch

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

    def test_event_weights_are_correct(self):
        """Test that event weights are assigned correctly."""
        self.assertEqual(self.processor.get_event_weight("fundraise"), 3.0)
        self.assertEqual(self.processor.get_event_weight("donate"), 3.0)
        self.assertEqual(self.processor.get_event_weight("upvote"), 2.0)
        self.assertEqual(self.processor.get_event_weight("share"), 2.0)
        self.assertEqual(self.processor.get_event_weight("download"), 1.5)
        self.assertEqual(self.processor.get_event_weight("click"), 1.0)
        self.assertEqual(self.processor.get_event_weight("scroll_impression"), 0.7)
        self.assertEqual(self.processor.get_event_weight("initial_impression"), 0.3)
        self.assertEqual(self.processor.get_event_weight("downvote"), -1.0)
        self.assertEqual(self.processor.get_event_weight("flag_content"), -2.5)

    def test_should_process_ml_relevant_events(self):
        """Test that ML-relevant events are identified correctly."""
        valid_event = {
            "event_type": "click",
            "user_id": str(self.user.id),
            "event_properties": {"item_id": "doc_123"},
        }
        self.assertTrue(self.processor.should_process_event(valid_event))

    def test_should_not_process_irrelevant_events(self):
        """Test that non-ML-relevant events are filtered out."""
        invalid_event = {
            "event_type": "page_view",  # Not in ML_RELEVANT_EVENTS
            "user_id": str(self.user.id),
            "event_properties": {"item_id": "doc_123"},
        }
        self.assertFalse(self.processor.should_process_event(invalid_event))

    def test_should_not_process_events_without_user_id(self):
        """Test that events without user_id are rejected."""
        event = {"event_type": "click", "event_properties": {"item_id": "doc_123"}}
        self.assertFalse(self.processor.should_process_event(event))

    def test_should_not_process_events_without_item_id(self):
        """Test that events without item_id are rejected."""
        event = {
            "event_type": "click",
            "user_id": str(self.user.id),
            "event_properties": {},
        }
        self.assertFalse(self.processor.should_process_event(event))

    @patch(
        "analytics.services.personalize_service.PersonalizeService.send_interaction_event"
    )
    def test_process_interaction_event_sends_to_personalize(self, mock_send):
        """Test that processing an interaction event sends to AWS Personalize."""
        mock_send.return_value = True

        event = {
            "event_type": "click",
            "user_id": str(self.user.id),
            "event_properties": {"item_id": "doc_123", "item_type": "paper"},
            "time": 1234567890000,
        }

        self.processor.process_event(event)

        # Verify AWS Personalize was called
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        self.assertEqual(call_args[1]["user_id"], str(self.user.id))
        self.assertEqual(call_args[1]["item_id"], "doc_123")
        self.assertEqual(call_args[1]["event_type"], "click")

    @patch(
        "analytics.services.personalize_service.PersonalizeService.send_impression_data"
    )
    def test_process_impression_event_sends_to_personalize(self, mock_send):
        """Test that processing an impression event sends to AWS Personalize."""
        mock_send.return_value = True

        event = {
            "event_type": "scroll_impression",
            "user_id": str(self.user.id),
            "event_properties": {"items_shown": ["doc_1", "doc_2", "doc_3"]},
            "time": 1234567890000,
        }

        self.processor.process_event(event)

        # Verify AWS Personalize was called
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        self.assertEqual(call_args[1]["user_id"], str(self.user.id))
        self.assertEqual(call_args[1]["items_shown"], ["doc_1", "doc_2", "doc_3"])

    def test_process_event_handles_nonexistent_user(self):
        """Test that processing handles nonexistent user gracefully."""
        event = {
            "event_type": "click",
            "user_id": "99999",  # Nonexistent user
            "event_properties": {"item_id": "doc_123"},
            "time": 1234567890000,
        }

        # Should not raise an exception
        self.processor.process_event(event)

    def test_positive_and_negative_weights(self):
        """Test that positive and negative event weights work correctly."""
        # Positive weight
        self.assertGreater(self.processor.get_event_weight("upvote"), 0)

        # Negative weight
        self.assertLess(self.processor.get_event_weight("downvote"), 0)
        self.assertLess(self.processor.get_event_weight("flag_content"), 0)
