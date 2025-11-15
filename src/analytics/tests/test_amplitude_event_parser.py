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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": timestamp_ms,
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
        }

        with self.assertLogs(
            "analytics.interactions.amplitude_event_parser", level=logging.WARNING
        ) as log:
            interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("No user_id or external_user_id (amplitude_id) found", log.output[0])

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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "_time": int(timezone.now().timestamp() * 1000),
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
            "amplitude_id": "test_amplitude_123",
            "_time": int(timezone.now().timestamp() * 1000),
        }

        # Mock datetime.fromtimestamp to raise an exception
        from unittest.mock import MagicMock

        # Create a mock datetime class that raises an exception on fromtimestamp
        mock_datetime = MagicMock()
        mock_datetime.fromtimestamp.side_effect = Exception("Unexpected error")
        mock_datetime.now.return_value = timezone.now()

        with patch(
            "analytics.interactions.amplitude_event_parser.datetime", mock_datetime
        ):

            with self.assertLogs(
                "analytics.interactions.amplitude_event_parser", level=logging.ERROR
            ) as log:
                interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
        self.assertIn("Unexpected error parsing event", log.output[0])
