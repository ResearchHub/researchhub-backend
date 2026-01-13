from datetime import datetime
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from analytics.constants.event_types import (
    DOCUMENT_TAB_CLICKED,
    FEED_ITEM_CLICK,
    FEED_ITEM_IMPRESSION,
    PAGE_VIEW,
)
from analytics.exceptions import EventProcessingError
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
            "time_": int(datetime.now().timestamp() * 1000),
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
            "time_": int(datetime.now().timestamp() * 1000),
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
            "time_": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.event, PAGE_VIEW)

    def test_process_event_with_document_tab_clicked_creates_interaction(self):
        """Test process_event creates UserInteractions for document_tab_clicked."""
        event = {
            "event_type": "document_tab_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time_": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        # Verify the created interaction
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.event, DOCUMENT_TAB_CLICKED)

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
            "time_": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()

        with self.assertRaises(EventProcessingError) as context:
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
            "time_": int(datetime.now().timestamp() * 1000),
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
            "time_": int(datetime.now().timestamp() * 1000),
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
        """Test process_event raises ValueError for invalid content_type."""
        event = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.content_type": "invalid_model",
                "related_work.id": str(self.post.id),
            },
            "time_": int(datetime.now().timestamp() * 1000),
        }

        initial_count = UserInteractions.objects.count()

        with self.assertRaises(EventProcessingError) as context:
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

    def test_process_event_with_impression_stores_pipe_delimited_string(self):
        """Test that impression array is stored as pipe-delimited string."""
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

        # Verify the created interaction has impression
        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, FEED_ITEM_CLICK)
        self.assertEqual(interaction.impression, "123|456|789")

    def test_process_event_without_impression_stores_none(self):
        """Test that events without impression store None."""
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

        # Verify the created interaction has None impression
        interaction = UserInteractions.objects.latest("created_date")
        self.assertIsNone(interaction.impression)

    def test_process_event_with_single_impression(self):
        """Test that single-item impression array is stored correctly."""
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
        self.assertEqual(interaction.impression, "123")

    def test_process_event_with_impression_and_recommendation_id(self):
        """Test that both impression and recommendation_id are stored."""
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
        self.assertEqual(interaction.impression, "123|456")
        self.assertEqual(interaction.personalize_rec_id, recommendation_id)

    def test_process_bulk_impression_event_creates_multiple_impression_records(
        self,
    ):
        """Test bulk_feed_impression creates multiple FEED_ITEM_IMPRESSION."""
        # Create a second post for testing
        post2 = create_post(created_by=self.user)

        event = {
            "user_id": str(self.user.id),
            "device_id": "test-device-id",
            "session_id": 1768253299243,
            "time": int(datetime.now().timestamp() * 1000),
            "platform": "Web",
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "device_type": "desktop",
                "feed_source": "home",
                "feed_tab": "for-you",
                "impression_count": 2,
                "impressions": [
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "contentType": "paper",
                        "feedPosition": 3,
                        "recommendationId": (
                            "RID-41-4408-ac5a-4b769df9c6f2-CID-4f7b66"
                        ),
                    },
                    {
                        "unifiedDocumentId": str(post2.unified_document.id),
                        "contentType": "paper",
                        "feedPosition": 4,
                        "recommendationId": (
                            "RID-41-4408-ac5a-4b769df9c6f2-CID-4f7b66"
                        ),
                    },
                ],
            },
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        # Should create 2 new interactions
        self.assertEqual(final_count, initial_count + 2)

        # Verify both interactions were created with correct event type
        impressions = UserInteractions.objects.filter(
            event=FEED_ITEM_IMPRESSION
        ).order_by("id")
        self.assertEqual(impressions.count(), 2)

        # Verify first impression
        impression1 = impressions[0]
        self.assertEqual(impression1.user, self.user)
        self.assertEqual(impression1.event, FEED_ITEM_IMPRESSION)
        self.assertEqual(impression1.unified_document, self.post.unified_document)
        self.assertIsNone(impression1.content_type)
        self.assertIsNone(impression1.object_id)
        self.assertFalse(impression1.is_synced_with_personalize)
        self.assertEqual(
            impression1.personalize_rec_id,
            "RID-41-4408-ac5a-4b769df9c6f2-CID-4f7b66",
        )

        # Verify second impression
        impression2 = impressions[1]
        self.assertEqual(impression2.user, self.user)
        self.assertEqual(impression2.event, FEED_ITEM_IMPRESSION)
        self.assertEqual(impression2.unified_document, post2.unified_document)
        self.assertIsNone(impression2.content_type)
        self.assertIsNone(impression2.object_id)

    def test_bulk_impression_events_named_correctly(self):
        """Test all records from bulk event have FEED_ITEM_IMPRESSION type."""
        post2 = create_post(created_by=self.user)

        event = {
            "user_id": str(self.user.id),
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "impressions": [
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "recommendationId": "rec-1",
                    },
                    {
                        "unifiedDocumentId": str(post2.unified_document.id),
                        "recommendationId": "rec-2",
                    },
                ],
            },
        }

        self.processor.process_event(event)

        # All created interactions should have FEED_ITEM_IMPRESSION event type
        impressions = UserInteractions.objects.filter(
            unified_document__in=[
                self.post.unified_document,
                post2.unified_document,
            ]
        )
        for impression in impressions:
            self.assertEqual(impression.event, FEED_ITEM_IMPRESSION)

    def test_bulk_impression_uses_correct_user_ids(self):
        """Test bulk impression with authenticated and anonymous users."""
        # Test with authenticated user (user_id)
        event_authenticated = {
            "user_id": str(self.user.id),
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "user_id": str(self.user.id),
                "impressions": [
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "recommendationId": "rec-1",
                    },
                ],
            },
        }

        self.processor.process_event(event_authenticated)

        interaction = UserInteractions.objects.filter(
            event=FEED_ITEM_IMPRESSION, user=self.user
        ).first()
        self.assertIsNotNone(interaction)
        self.assertEqual(interaction.user, self.user)

        # Test with anonymous user (external_user_id)
        event_anonymous = {
            "amplitude_id": "external-user-123",
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "impressions": [
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "recommendationId": "rec-2",
                    },
                ],
            },
        }

        self.processor.process_event(event_anonymous)

        interaction = UserInteractions.objects.filter(
            event=FEED_ITEM_IMPRESSION, external_user_id="external-user-123"
        ).first()
        self.assertIsNotNone(interaction)
        self.assertEqual(interaction.external_user_id, "external-user-123")
        self.assertIsNone(interaction.user)

    def test_bulk_impression_daily_deduplication(self):
        """Test processing same bulk event twice doesn't create duplicates."""
        event = {
            "user_id": str(self.user.id),
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "impressions": [
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "recommendationId": "rec-1",
                    },
                ],
            },
        }

        # Process event first time
        self.processor.process_event(event)
        first_count = UserInteractions.objects.filter(
            event=FEED_ITEM_IMPRESSION
        ).count()
        self.assertEqual(first_count, 1)

        # Process same event again (same day)
        self.processor.process_event(event)
        second_count = UserInteractions.objects.filter(
            event=FEED_ITEM_IMPRESSION
        ).count()

        # Should not create duplicate due to daily uniqueness constraint
        self.assertEqual(second_count, first_count)

    def test_bulk_impression_missing_unified_document_id(self):
        """Test impressions without unifiedDocumentId are skipped."""
        event = {
            "user_id": str(self.user.id),
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "impressions": [
                    {
                        "contentType": "paper",
                        "feedPosition": 3,
                        # Missing unifiedDocumentId
                    },
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "recommendationId": "rec-1",
                    },
                ],
            },
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        # Should only create 1 interaction (skip the one without unified_document_id)
        self.assertEqual(final_count, initial_count + 1)

    def test_bulk_impression_invalid_unified_document_id_format(self):
        """Test impressions with non-numeric unified_document_id are skipped."""
        event = {
            "user_id": str(self.user.id),
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "impressions": [
                    {
                        "unifiedDocumentId": "not-a-number",  # Invalid format
                        "recommendationId": "rec-1",
                    },
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "recommendationId": "rec-2",
                    },
                ],
            },
        }

        initial_count = UserInteractions.objects.count()
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        # Should only create 1 interaction (skip the invalid format one)
        self.assertEqual(final_count, initial_count + 1)

    def test_bulk_impression_empty_impressions_array(self):
        """Test that event with empty impressions array doesn't fail."""
        event = {
            "user_id": str(self.user.id),
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "impressions": [],
            },
        }

        initial_count = UserInteractions.objects.count()
        # Should not raise exception
        self.processor.process_event(event)
        final_count = UserInteractions.objects.count()

        # Should not create any interactions
        self.assertEqual(final_count, initial_count)

    def test_bulk_impression_no_user_id_raises_error(self):
        """Test bulk impression without user_id/external_user_id raises error."""
        event = {
            "time": int(datetime.now().timestamp() * 1000),
            "event_type": "bulk_feed_impression",
            "event_properties": {
                "impressions": [
                    {
                        "unifiedDocumentId": str(self.post.unified_document.id),
                        "recommendationId": "rec-1",
                    },
                ],
            },
        }

        with self.assertRaises(EventProcessingError) as context:
            self.processor.process_event(event)

        self.assertIn("No user_id or external_user_id", str(context.exception))
