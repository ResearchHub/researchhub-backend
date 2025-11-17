from datetime import datetime
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from analytics.constants.event_types import FEED_ITEM_CLICK, PAGE_VIEW
from analytics.models import UserInteractions
from analytics.services.event_processor import EventProcessor
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class EventProcessorTestCase(TestCase):
    """Test cases for the EventProcessor service."""

    def setUp(self):
        self.processor = EventProcessor()
        self.user = create_random_default_user("test_user")
        self.post = create_post(created_by=self.user)
        self.content_type = ContentType.objects.get_for_model(self.post)

    def test_process_event_creates_user_interaction(self):
        """Test that process_event creates UserInteractions record."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, FEED_ITEM_CLICK)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)
        self.assertFalse(interaction.is_synced_with_personalize)
        self.assertIsNone(interaction.personalize_rec_id)

    def test_process_event_handles_duplicate_interactions(self):
        """Test that process_event handles duplicate interactions gracefully."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        # Process the same event twice
        self.processor.process_event(event)
        initial_count = UserInteractions.objects.count()

        # Second processing should not create a duplicate due to daily uniqueness
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    def test_process_event_with_page_viewed_creates_interaction(self):
        """Test process_event creates UserInteractions for work_document_viewed."""
        event = {
            "event_type": "work_document_viewed",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.event, PAGE_VIEW)

    def test_process_event_raises_exception_for_invalid_event(self):
        """Test that process_event raises ValueError for invalid events."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": "99999",  # Non-existent user
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()

        with self.assertRaises(ValueError) as context:
            self.processor.process_event(event)

        self.assertIn("Could not parse event", str(context.exception))

        final_count = UserInteractions.objects.count()
        self.assertEqual(final_count, initial_count)  # No new interaction created

    def test_process_event_logs_correctly(self):
        """Test that process_event logs the event correctly."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        with patch("analytics.services.event_processor.logger") as mock_logger:
            self.processor.process_event(event)

            # Verify logging calls
            mock_logger.debug.assert_any_call(
                f"Successfully processed interaction: feed_item_clicked for user "
                f"{self.user.id}"
            )

    def test_process_event_creates_user_interaction_with_flat_format(self):
        """Test that process_event creates UserInteractions record with flat format."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.content_type": "researchhubpost",
                "related_work.id": str(self.post.id),
                "related_work.unified_document_id": str(self.post.unified_document.id),
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, FEED_ITEM_CLICK)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)

    def test_process_event_raises_exception_for_flat_format_invalid_content_type(self):
        """Test process_event raises ValueError for flat format invalid content_type."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.content_type": "invalid_model",
                "related_work.id": str(self.post.id),
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()

        with self.assertRaises(ValueError) as context:
            self.processor.process_event(event)

        self.assertIn("Could not parse event", str(context.exception))

        final_count = UserInteractions.objects.count()
        self.assertEqual(final_count, initial_count)  # No new interaction created

    def test_process_event_stores_recommendation_id_as_personalize_rec_id(self):
        """Test that recommendation_id from event_properties is stored as personalize_rec_id."""
        recommendation_id = "rec_12345"
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "recommendation_id": recommendation_id,
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction has personalize_rec_id
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, FEED_ITEM_CLICK)
        self.assertEqual(interaction.personalize_rec_id, recommendation_id)

    def test_process_event_without_recommendation_id_stores_none(self):
        """Test that events without recommendation_id store None for personalize_rec_id."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction has None personalize_rec_id
        interaction = UserInteractions.objects.latest("created_date")
        self.assertIsNone(interaction.personalize_rec_id)

    def test_process_event_with_numeric_recommendation_id_converts_to_string(self):
        """Test that numeric recommendation_id is converted to string."""
        recommendation_id = 12345
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "recommendation_id": recommendation_id,
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction has string personalize_rec_id
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.personalize_rec_id, "12345")

    def test_process_event_with_recommendation_id_updates_existing_interaction(self):
        """Test that recommendation_id is stored when updating existing interaction."""
        recommendation_id = "rec_67890"
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "recommendation_id": recommendation_id,
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        # Process event first time
        self.processor.process_event(event)
        initial_count = UserInteractions.objects.count()

        # Process same event again (should update, not create duplicate)
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

        # Verify the interaction still has personalize_rec_id
        interaction = UserInteractions.objects.get(
            user=self.user,
            event=FEED_ITEM_CLICK,
            unified_document=self.post.unified_document,
        )
        self.assertEqual(interaction.personalize_rec_id, recommendation_id)

    def test_process_event_with_impressions_stores_pipe_delimited_string(self):
        """Test that impressions array is stored as pipe-delimited string."""
        impression_array = ["123", "456", "789"]
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "impression": impression_array,
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction has impressions
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, FEED_ITEM_CLICK)
        self.assertEqual(interaction.impressions, "123|456|789")

    def test_process_event_without_impressions_stores_none(self):
        """Test that events without impressions store None."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction has None impressions
        interaction = UserInteractions.objects.latest("created_date")
        self.assertIsNone(interaction.impressions)

    def test_process_event_with_single_impression(self):
        """Test that single-item impressions array is stored correctly."""
        impression_array = ["123"]
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "impression": impression_array,
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        self.processor.process_event(event)

        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.impressions, "123")

    def test_process_event_with_impressions_and_recommendation_id(self):
        """Test that both impressions and recommendation_id are stored."""
        impression_array = ["123", "456"]
        recommendation_id = "rec_12345"
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "impression": impression_array,
                "recommendation_id": recommendation_id,
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time": int(datetime.now().timestamp() * 1000),
        }

        self.processor.process_event(event)

        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.impressions, "123|456")
        self.assertEqual(interaction.personalize_rec_id, recommendation_id)
