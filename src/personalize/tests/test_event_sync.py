from datetime import datetime
from unittest.mock import Mock, patch

import pytz
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from analytics.constants.event_types import FEED_ITEM_CLICK, PAGE_VIEW, UPVOTE
from analytics.models import UserInteractions
from analytics.services.event_processor import EventProcessor
from analytics.tests.helpers import create_prefetched_paper
from personalize.clients.sync_client import SyncClient
from personalize.tasks import sync_interaction_event_to_personalize_task
from personalize.utils.personalize_utils import (
    build_session_id_for_anonymous,
    build_session_id_for_user,
)
from user.tests.helpers import create_random_default_user


class EventSyncTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("test_user")
        self.paper = create_prefetched_paper(title="Test Paper")
        self.content_type = ContentType.objects.get_for_model(self.paper.paper)

        self.mock_sync_result_success = {
            "success": True,
            "synced": 1,
            "failed": 0,
            "errors": [],
        }

        self.mock_sync_result_failure = {
            "success": False,
            "synced": 0,
            "failed": 1,
            "errors": ["AWS API error"],
        }

    def _create_amplitude_event(self, event_type, timestamp_offset=0):
        return {
            "event_type": event_type,
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.paper.id),
                    "content_type": "paper",
                    "id": str(self.paper.paper.id),
                },
            },
            "_time": int(
                (datetime.now(pytz.UTC).timestamp() + timestamp_offset) * 1000
            ),
        }

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_only_specific_events_synced_from_amplitude(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_success
        MockSyncService.return_value = mock_service

        processor = EventProcessor()
        feed_click_event = self._create_amplitude_event("feed_item_clicked")
        page_view_event = self._create_amplitude_event("work_document_viewed", 1)

        # Act
        processor.process_event(feed_click_event)
        processor.process_event(page_view_event)

        # Assert
        self.assertEqual(mock_service.sync_event.call_count, 2)
        synced_interactions = UserInteractions.objects.filter(
            user=self.user, unified_document=self.paper
        )
        self.assertEqual(synced_interactions.count(), 2)
        event_types = set(synced_interactions.values_list("event", flat=True))
        self.assertIn(FEED_ITEM_CLICK, event_types)
        self.assertIn(PAGE_VIEW, event_types)
        self.assertNotIn(UPVOTE, event_types)

    @patch("personalize.clients.sync_client.create_client")
    @patch("personalize.clients.sync_client.settings")
    def test_sync_client_creates_correct_batches_for_events(
        self, mock_settings, mock_create_client
    ):
        # Arrange
        mock_aws_client = Mock()
        mock_create_client.return_value = mock_aws_client
        mock_settings.AWS_PERSONALIZE_DATASET_ARN = "arn:test:dataset"
        mock_settings.AWS_PERSONALIZE_TRACKING_ID = "test-tracking-id"

        sync_client = SyncClient()
        events = [
            {
                "eventId": str(i),
                "eventType": "FEED_ITEM_CLICK",
                "itemId": "123",
                "sentAt": int(datetime.now().timestamp()),
            }
            for i in range(25)
        ]

        # Act
        result = sync_client.put_events("user_123", "sess_user_123_2025_11_18", events)

        # Assert
        self.assertEqual(mock_aws_client.put_events.call_count, 3)
        call_args_list = mock_aws_client.put_events.call_args_list
        self.assertEqual(len(call_args_list[0][1]["eventList"]), 10)
        self.assertEqual(len(call_args_list[1][1]["eventList"]), 10)
        self.assertEqual(len(call_args_list[2][1]["eventList"]), 5)
        self.assertEqual(result["synced"], 25)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(result["success"])

    def test_session_id_formatting_for_authenticated_users(self):
        # Arrange
        user_id = 12345
        test_date = datetime(2025, 11, 18, 14, 30, 0, tzinfo=pytz.UTC)

        # Act
        session_id = build_session_id_for_user(user_id, test_date)

        # Assert
        self.assertEqual(session_id, "sess_user_12345_2025_11_18")

        different_date = datetime(2025, 11, 19, 10, 0, 0, tzinfo=pytz.UTC)
        different_session = build_session_id_for_user(user_id, different_date)
        self.assertNotEqual(session_id, different_session)
        self.assertEqual(different_session, "sess_user_12345_2025_11_19")

    def test_session_id_formatting_for_anonymous_users(self):
        # Arrange
        external_user_id = "amp_anon_xyz789"

        # Act
        session_id = build_session_id_for_anonymous(external_user_id)

        # Assert
        self.assertEqual(session_id, f"sess_anon_{external_user_id}")
        self.assertRegex(session_id, r"^sess_anon_.+$")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_sync_only_triggered_when_interaction_created(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_success
        MockSyncService.return_value = mock_service

        processor = EventProcessor()
        event_payload = self._create_amplitude_event("feed_item_clicked")

        # Act
        processor.process_event(event_payload)
        first_call_count = mock_service.sync_event.call_count

        processor.process_event(event_payload)
        second_call_count = mock_service.sync_event.call_count

        # Assert
        self.assertEqual(first_call_count, 1)
        self.assertEqual(second_call_count, 1)
        interactions = UserInteractions.objects.filter(
            user=self.user, unified_document=self.paper, event=FEED_ITEM_CLICK
        )
        self.assertEqual(interactions.count(), 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_interaction_marked_as_synced_on_success(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_success
        MockSyncService.return_value = mock_service

        interaction = UserInteractions.objects.create(
            user=self.user,
            event=FEED_ITEM_CLICK,
            unified_document=self.paper,
            content_type=self.content_type,
            object_id=self.paper.paper.id,
            event_timestamp=datetime.now(pytz.UTC),
            is_synced_with_personalize=False,
        )

        # Act
        sync_interaction_event_to_personalize_task(interaction.id)

        # Assert
        mock_service.sync_event.assert_called_once()
        interaction.refresh_from_db()
        self.assertTrue(interaction.is_synced_with_personalize)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_interaction_not_marked_synced_on_failure(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_failure
        MockSyncService.return_value = mock_service

        interaction = UserInteractions.objects.create(
            user=self.user,
            event=PAGE_VIEW,
            unified_document=self.paper,
            content_type=self.content_type,
            object_id=self.paper.paper.id,
            event_timestamp=datetime.now(pytz.UTC),
            is_synced_with_personalize=False,
        )

        # Act
        with self.assertRaises(Exception):
            sync_interaction_event_to_personalize_task(interaction.id)

        # Assert
        interaction.refresh_from_db()
        self.assertFalse(interaction.is_synced_with_personalize)
