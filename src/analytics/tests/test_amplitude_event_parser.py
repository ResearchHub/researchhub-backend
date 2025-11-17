import logging
from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from analytics.constants.event_types import FEED_ITEM_CLICK, PAGE_VIEW
from analytics.interactions.amplitude_event_parser import (
    AmplitudeEvent,
    AmplitudeEventParser,
)
from researchhub_document.helpers import create_post

User = get_user_model()


class AmplitudeEventParserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@researchhub.com",
            first_name="Test",
            last_name="User",
        )
        self.post = create_post(created_by=self.user)
        self.content_type = ContentType.objects.get_for_model(self.post)
        self.parser = AmplitudeEventParser()

    def test_maps_feed_item_clicked_with_unified_document_id(self):
        """Test mapping feed_item_clicked event with direct unified_document_id."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event_type, FEED_ITEM_CLICK)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)

    def test_maps_feed_item_clicked_with_content_type_and_id(self):
        """Test mapping feed_item_clicked event with content_type + id combo."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event_type, FEED_ITEM_CLICK)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)

    def test_maps_page_viewed_event(self):
        """Test mapping work_document_viewed event."""
        event = {
            "event_type": "work_document_viewed",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event_type, PAGE_VIEW)
        self.assertEqual(interaction.unified_document, self.post.unified_document)

    def test_converts_event_type_to_uppercase(self):
        """Test that lowercase Amplitude event types are converted to uppercase."""
        event = {
            "event_type": "feed_item_clicked",  # lowercase
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertEqual(interaction.event_type, "FEED_ITEM_CLICK")

    def test_converts_timestamp_from_milliseconds(self):
        """Test that timestamp is converted from milliseconds to datetime."""
        timestamp_ms = int(timezone.now().timestamp() * 1000)
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": timestamp_ms,
        }

        interaction = self.parser.parse_amplitude_event(event)

        expected_datetime = datetime.fromtimestamp(timestamp_ms / 1000)
        self.assertEqual(interaction.event_timestamp, expected_datetime)

    def test_event_without_related_work_returns_none(self):
        """Test that events without related_work return None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("No related_work data found", log.output[0])

    def test_event_without_user_id_returns_none(self):
        """Test that events without user_id return None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("No user_id in event_properties", log.output[0])

    def test_invalid_event_type_returns_none(self):
        """Test that invalid event types return None."""
        event = {
            "event_type": "invalid_event",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("Event type 'invalid_event' not in mapping", log.output[0])

    def test_nonexistent_user_returns_none(self):
        """Test that events with non-existent user_id return None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": 99999,  # Non-existent user
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("Invalid user_id", log.output[0])

    def test_nonexistent_unified_document_returns_none(self):
        """Test that events with non-existent unified_document_id return None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": 99999,  # Non-existent document
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("Invalid unified_document_id", log.output[0])

    def test_handles_missing_timestamp(self):
        """Test that missing timestamp uses current time."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            # No time field
        }

        with patch(
            "analytics.interactions.amplitude_event_parser.datetime"
        ) as mock_datetime:
            mock_now = timezone.now()
            mock_datetime.now.return_value = mock_now
            mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp

            interaction = self.parser.parse_amplitude_event(event)

            self.assertEqual(interaction.event_timestamp, mock_now)

    def test_handles_invalid_content_type(self):
        """Test that invalid content_type returns None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "content_type": "invalid_model",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("Invalid content_type", log.output[0])

    def test_maps_feed_item_clicked_with_flat_format(self):
        """Test mapping feed_item_clicked event with flat dot-notation format."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work.content_type": "researchhubpost",
                "related_work.id": self.post.id,
                "related_work.unified_document_id": self.post.unified_document.id,
                "author_id": "153397",
                "device_type": "desktop",
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event_type, FEED_ITEM_CLICK)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)

    def test_maps_page_viewed_with_flat_format(self):
        """Test mapping page_viewed event with flat dot-notation format."""
        event = {
            "event_type": "work_document_viewed",
            "event_properties": {
                "user_id": self.user.id,
                "related_work.content_type": "researchhubpost",
                "related_work.id": self.post.id,
                "related_work.unified_document_id": self.post.unified_document.id,
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event_type, PAGE_VIEW)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)

    def test_maps_feed_item_clicked_with_flat_format_content_type_and_id_only(self):
        """Test mapping feed_item_clicked with flat format using content_type + id."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work.content_type": "researchhubpost",
                "related_work.id": self.post.id,
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event_type, FEED_ITEM_CLICK)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)

    def test_flat_format_without_related_work_returns_none(self):
        """Test that flat format events without related_work keys return None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "author_id": "153397",
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("No related_work data found", log.output[0])

    def test_flat_format_handles_invalid_content_type(self):
        """Test that flat format with invalid content_type returns None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work.content_type": "invalid_model",
                "related_work.id": self.post.id,
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("Invalid content_type", log.output[0])

    def test_unexpected_error_logs_at_error_level(self):
        """Test that unexpected errors during parsing log at ERROR level."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        # Mock datetime.fromtimestamp to raise an exception
        with patch(
            "analytics.interactions.amplitude_event_parser.datetime"
        ) as mock_datetime:
            mock_datetime.fromtimestamp.side_effect = Exception("Unexpected error")
            mock_datetime.now.return_value = timezone.now()

            with self.assertLogs(
                "analytics.interactions.amplitude_event_parser", level=logging.ERROR
            ) as log:
                interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("Unexpected error parsing event", log.output[0])

    def test_extracts_recommendation_id_from_event_properties(self):
        """Test that recommendation_id is extracted from event_properties."""
        recommendation_id = "rec_12345"
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "recommendation_id": recommendation_id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.personalize_rec_id, recommendation_id)

    def test_extracts_recommendation_id_with_numeric_value(self):
        """Test that numeric recommendation_id is converted to string."""
        recommendation_id = 12345
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "recommendation_id": recommendation_id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.personalize_rec_id, "12345")

    def test_missing_recommendation_id_defaults_to_none(self):
        """Test that events without recommendation_id have None personalize_rec_id."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertIsNone(interaction.personalize_rec_id)

    def test_empty_recommendation_id_defaults_to_none(self):
        """Test that empty string recommendation_id is handled."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "recommendation_id": "",
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.personalize_rec_id, "")

    def test_none_recommendation_id_defaults_to_none(self):
        """Test that None recommendation_id results in None personalize_rec_id."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "recommendation_id": None,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertIsNone(interaction.personalize_rec_id)

    def test_recommendation_id_with_flat_format(self):
        """Test that recommendation_id works with flat format event_properties."""
        recommendation_id = "rec_67890"
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "recommendation_id": recommendation_id,
                "related_work.content_type": "researchhubpost",
                "related_work.id": self.post.id,
                "related_work.unified_document_id": self.post.unified_document.id,
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.personalize_rec_id, recommendation_id)

    def test_extracts_impression_from_event_properties(self):
        """Test that impression array is extracted and converted to pipe-delimited string."""
        impression_array = ["123", "456", "789"]
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "impression": impression_array,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.impression, "123|456|789")

    def test_extracts_impression_with_single_item(self):
        """Test that single-item impression array is converted correctly."""
        impression_array = ["123"]
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "impression": impression_array,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.impression, "123")

    def test_missing_impression_defaults_to_none(self):
        """Test that events without impression have None impression."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertIsNone(interaction.impression)

    def test_non_list_impression_ignored(self):
        """Test that non-list impression is ignored."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "impression": "not_an_array",
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertIsNone(interaction.impression)

    def test_empty_impression_array_defaults_to_none(self):
        """Test that empty impression array results in None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "impression": [],
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertIsNone(interaction.impression)

    def test_impression_with_numeric_values_converted_to_string(self):
        """Test that numeric impression values are converted to strings."""
        impression_array = [123, 456, 789]
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": self.user.id,
                "impression": impression_array,
                "related_work": {
                    "unified_document_id": self.post.unified_document.id,
                    "content_type": "researchhubpost",
                    "id": self.post.id,
                },
            },
            "time": int(timezone.now().timestamp() * 1000),
        }

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsInstance(interaction, AmplitudeEvent)
        self.assertEqual(interaction.impression, "123|456|789")
