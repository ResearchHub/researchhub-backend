from datetime import UTC, datetime
from unittest.mock import Mock, patch

from django.test import TestCase

from personalize.clients.sync_client import SyncClient
from personalize.utils.personalize_utils import (
    build_session_id_for_anonymous,
    build_session_id_for_user,
)


class EventSyncTests(TestCase):
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
        test_date = datetime(2025, 11, 18, 14, 30, 0, tzinfo=UTC)

        # Act
        session_id = build_session_id_for_user(user_id, test_date)

        # Assert
        self.assertEqual(session_id, "sess_user_12345_2025_11_18")

        different_date = datetime(2025, 11, 19, 10, 0, 0, tzinfo=UTC)
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
