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

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)

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

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)

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

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)

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

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)

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

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)

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

        interaction = self.parser.parse_amplitude_event(event)

        self.assertIsNone(interaction)
