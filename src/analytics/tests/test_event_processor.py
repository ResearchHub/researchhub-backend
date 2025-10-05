from unittest.mock import patch

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
        self.assertEqual(self.processor.get_event_weight("vote_action"), 2.0)
        self.assertEqual(self.processor.get_event_weight("feed_item_clicked"), 1.5)
        self.assertEqual(self.processor.get_event_weight("proposal_funded"), 3.0)
        self.assertEqual(self.processor.get_event_weight("comment_created"), 2.5)
        self.assertEqual(self.processor.get_event_weight("peer_review_created"), 2.8)

    def test_should_process_ml_relevant_events(self):
        """Test that ML-relevant events are identified correctly."""
        valid_event = {
            "event_type": "vote_action",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.unified_document_id": "doc_123",
                "related_work.content_type": "paper",
            },
        }
        self.assertTrue(self.processor.should_process_event(valid_event))

    def test_should_process_events_with_content_type_and_id(self):
        """Test that events with content_type and id in related_work are processed."""
        valid_event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.content_type": "paper",
                "related_work.id": "123",
            },
        }
        self.assertTrue(self.processor.should_process_event(valid_event))

    def test_should_not_process_events_without_content_type(self):
        """Test that events without content_type are rejected."""
        invalid_event = {
            "event_type": "vote_action",
            "user_id": str(self.user.id),
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.unified_document_id": "doc_123",
                # Missing content_type
            },
        }
        self.assertFalse(self.processor.should_process_event(invalid_event))

    def test_should_not_process_irrelevant_events(self):
        """Test that non-ML-relevant events are filtered out."""
        invalid_event = {
            "event_type": "page_view",  # Not in ML_RELEVANT_EVENTS
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.unified_document_id": "doc_123",
                "related_work.content_type": "paper",
            },
        }
        self.assertFalse(self.processor.should_process_event(invalid_event))

    def test_should_not_process_events_without_user_id(self):
        """Test that events without user_id are rejected."""
        event = {
            "event_type": "vote_action",
            "event_properties": {
                "related_work.unified_document_id": "doc_123",
                "related_work.content_type": "paper",
            },
        }
        self.assertFalse(self.processor.should_process_event(event))

    def test_should_not_process_events_without_related_work(self):
        """Test that events without related_work are rejected."""
        event = {
            "event_type": "vote_action",
            "event_properties": {"user_id": str(self.user.id)},
        }
        self.assertFalse(self.processor.should_process_event(event))

    def test_should_not_process_events_with_empty_related_work(self):
        """Test that events with empty related_work are rejected."""
        event = {
            "event_type": "vote_action",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.unified_document_id": None,
                "related_work.content_type": None,
                "related_work.id": None,
            },
        }
        self.assertFalse(self.processor.should_process_event(event))

    @patch("django.conf.settings.DEVELOPMENT", False)
    @patch(
        "analytics.services.personalize_service.PersonalizeService.send_interaction_event"
    )
    def test_process_interaction_event_sends_to_personalize(self, mock_send):
        """Test that processing an interaction event sends to AWS Personalize."""
        mock_send.return_value = True

        event = {
            "event_type": "vote_action",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.unified_document_id": "doc_123",
                "related_work.content_type": "paper",
            },
            "time": 1234567890000,
        }

        self.processor.process_event(event)

        # Verify AWS Personalize was called
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        self.assertEqual(call_args[1]["user_id"], str(self.user.id))
        self.assertEqual(call_args[1]["item_id"], "doc_123")
        self.assertEqual(call_args[1]["event_type"], "vote_action")

    def test_process_event_handles_nonexistent_user(self):
        """Test that processing handles nonexistent user gracefully."""
        event = {
            "event_type": "vote_action",
            "event_properties": {
                "user_id": "99999",  # Nonexistent user
                "related_work.unified_document_id": "doc_123",
                "related_work.content_type": "paper",
            },
            "time": 1234567890000,
        }

        # Should not raise an exception
        self.processor.process_event(event)

    def test_positive_weights(self):
        """Test that all event weights are positive."""
        # All our events should have positive weights
        self.assertGreater(self.processor.get_event_weight("vote_action"), 0)
        self.assertGreater(self.processor.get_event_weight("feed_item_clicked"), 0)
        self.assertGreater(self.processor.get_event_weight("proposal_funded"), 0)
        self.assertGreater(self.processor.get_event_weight("comment_created"), 0)
        self.assertGreater(self.processor.get_event_weight("peer_review_created"), 0)
