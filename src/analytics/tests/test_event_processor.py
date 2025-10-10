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
        self.assertEqual(self.processor.get_event_weight("bounty_created"), 3.0)
        self.assertEqual(self.processor.get_event_weight("comment_created"), 2.5)
        self.assertEqual(self.processor.get_event_weight("peer_review_created"), 3.0)

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

        # Verify AWS Personalize was called with correct parameters
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        self.assertEqual(call_args[1]["user_id"], str(self.user.id))
        self.assertEqual(call_args[1]["item_id"], "doc_123")
        self.assertEqual(call_args[1]["event_type"], "vote_action")
        self.assertIn("properties", call_args[1])
        self.assertIsInstance(call_args[1]["properties"], dict)

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

    # NEW TESTS TO COVER MISSING LINES

    def test_get_event_weight_with_special_vote_logic(self):
        """Test special weight logic for vote_action events."""
        # Test neutral vote (should return negative weight)
        weight = self.processor.get_event_weight(
            "vote_action", {"vote_type": "NEUTRAL"}
        )
        self.assertEqual(weight, -2.0)  # Negative of vote_action weight

        # Test upvote (should return normal weight)
        weight = self.processor.get_event_weight("vote_action", {"vote_type": "UPVOTE"})
        self.assertEqual(weight, 2.0)

        # Test unknown vote type (should return base weight)
        weight = self.processor.get_event_weight(
            "vote_action", {"vote_type": "UNKNOWN"}
        )
        self.assertEqual(weight, 2.0)

    def test_get_event_weight_with_special_comment_logic(self):
        """Test special weight logic for comment_created events."""
        # Test bounty comment (should return bounty_created weight)
        weight = self.processor.get_event_weight(
            "comment_created", {"comment_type": "bounty"}
        )
        self.assertEqual(weight, 3.0)  # Same as bounty_created

        # Test regular comment (should return normal weight)
        weight = self.processor.get_event_weight(
            "comment_created", {"comment_type": "GENERIC_COMMENT"}
        )
        self.assertEqual(weight, 2.5)

        # Test missing comment_type (should return normal weight)
        weight = self.processor.get_event_weight("comment_created", {})
        self.assertEqual(weight, 2.5)

        # Test empty comment_type (should return normal weight)
        weight = self.processor.get_event_weight(
            "comment_created", {"comment_type": ""}
        )
        self.assertEqual(weight, 2.5)

        # Test None comment_type (should return normal weight)
        weight = self.processor.get_event_weight(
            "comment_created", {"comment_type": None}
        )
        self.assertEqual(weight, 2.5)

    def test_get_event_weight_without_event_props(self):
        """Test get_event_weight without event_props."""
        weight = self.processor.get_event_weight("vote_action")
        self.assertEqual(weight, 2.0)

    def test_transform_to_personalize_format_feed_item_clicked(self):
        """Test transformation for feed_item_clicked events matches AWS schema."""
        event_props = {
            "user_id": "123",
            "related_work.unified_document_id": "doc_123",
            "related_work.content_type": "paper",
            "feed_position": 1,
            "feed_source": "home",
            "feed_tab": "trending",
            "device_type": "desktop",
        }

        result = self.processor._transform_to_personalize_format(
            event_type="feed_item_clicked",
            user_id="123",
            item_id="doc_123",
            content_type="paper",
            weight=1.5,
            timestamp=1234567890000,
            event_props=event_props,
        )

        # Check AWS Personalize schema compliance
        self.assertEqual(result["USER_ID"], "123")
        self.assertEqual(result["ITEM_ID"], "doc_123")
        self.assertEqual(result["EVENT_TYPE"], "feed_item_clicked")
        self.assertEqual(result["EVENT_VALUE"], 1.5)
        self.assertEqual(result["DEVICE"], "desktop")
        self.assertEqual(result["TIMESTAMP"], 1234567890000)
        self.assertIsNone(result["IMPRESSION"])
        self.assertIsNone(result["RECOMMENDATION_ID"])

    def test_transform_to_personalize_format_peer_review_created(self):
        """Test transformation for peer_review_created events matches AWS schema."""
        event_props = {
            "user_id": "123",
            "related_work.unified_document_id": "doc_123",
            "related_work.content_type": "paper",
            "score": 4.5,
            "device_type": "desktop",
        }

        result = self.processor._transform_to_personalize_format(
            event_type="peer_review_created",
            user_id="123",
            item_id="doc_123",
            content_type="paper",
            weight=3.0,
            timestamp=1234567890000,
            event_props=event_props,
        )

        # Check AWS Personalize schema compliance
        self.assertEqual(result["USER_ID"], "123")
        self.assertEqual(result["ITEM_ID"], "doc_123")
        self.assertEqual(result["EVENT_TYPE"], "peer_review_created")
        self.assertEqual(result["EVENT_VALUE"], 3.0)
        self.assertEqual(result["DEVICE"], "desktop")
        self.assertEqual(result["TIMESTAMP"], 1234567890000)
        self.assertIsNone(result["IMPRESSION"])
        self.assertIsNone(result["RECOMMENDATION_ID"])

    def test_transform_to_personalize_format_default_case(self):
        """Test transformation for default case matches AWS Personalize schema."""
        event_props = {
            "user_id": "123",
            "related_work.unified_document_id": "doc_123",
            "related_work.content_type": "paper",
            "device_type": "mobile",
        }

        result = self.processor._transform_to_personalize_format(
            event_type="unknown_event",
            user_id="123",
            item_id="doc_123",
            content_type="paper",
            weight=1.0,
            timestamp=1234567890000,
            event_props=event_props,
        )

        # Check AWS Personalize schema compliance
        self.assertEqual(result["USER_ID"], "123")
        self.assertEqual(result["ITEM_ID"], "doc_123")
        self.assertEqual(result["EVENT_TYPE"], "unknown_event")
        self.assertEqual(result["EVENT_VALUE"], 1.0)
        self.assertEqual(result["DEVICE"], "mobile")
        self.assertEqual(result["TIMESTAMP"], 1234567890000)
        self.assertIsNone(result["IMPRESSION"])
        self.assertIsNone(result["RECOMMENDATION_ID"])

    @patch("django.conf.settings.DEVELOPMENT", False)
    @patch(
        "analytics.services.personalize_service.PersonalizeService.send_impression_data"
    )
    def test_process_impression_event_sends_to_personalize(self, mock_send):
        """Test that processing an impression event sends to AWS Personalize."""
        mock_send.return_value = True

        event_props = {
            "user_id": "123",
            "items_shown": ["doc_1", "doc_2", "doc_3"],
        }

        self.processor._process_impression_event(
            user_id="123",
            event_type="scroll_impression",
            event_props=event_props,
            timestamp=1234567890000,
        )

        # Verify AWS Personalize was called
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        self.assertEqual(call_args[1]["user_id"], "123")
        self.assertEqual(call_args[1]["items_shown"], ["doc_1", "doc_2", "doc_3"])
        self.assertEqual(call_args[1]["timestamp"], 1234567890000)

    @patch("django.conf.settings.DEVELOPMENT", True)
    @patch(
        "analytics.services.personalize_service.PersonalizeService.send_impression_data"
    )
    def test_process_impression_event_skips_in_development(self, mock_send):
        """Test that impression events are not sent to Personalize in development."""
        event_props = {
            "user_id": "123",
            "items_shown": ["doc_1", "doc_2", "doc_3"],
        }

        self.processor._process_impression_event(
            user_id="123",
            event_type="scroll_impression",
            event_props=event_props,
            timestamp=1234567890000,
        )

        # Verify AWS Personalize was NOT called in development
        mock_send.assert_not_called()
