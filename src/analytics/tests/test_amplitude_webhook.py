import json
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from user.tests.helpers import create_random_default_user


class AmplitudeWebhookTestCase(TestCase):
    """
    Test cases for the Amplitude webhook endpoint.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("amplitude_webhook")
        self.user = create_random_default_user("test_user")

    def test_webhook_requires_post_method(self):
        """Test that the webhook only accepts POST requests."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_webhook_rejects_empty_payload(self):
        """Test that the webhook rejects empty payload."""
        response = self.client.post(
            self.url, data=json.dumps({}), content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No events", response.data["message"])

    def test_webhook_rejects_invalid_json(self):
        """Test that the webhook rejects invalid JSON."""
        response = self.client.post(
            self.url, data="invalid json", content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid JSON", response.data["message"])

    @patch("analytics.services.event_processor.EventProcessor.process_event")
    def test_webhook_processes_valid_events(self, mock_process):
        """Test that the webhook processes valid events."""
        payload = {
            "events": [
                {
                    "event_type": "click",
                    "user_id": str(self.user.id),
                    "event_properties": {"item_id": "doc_123", "item_type": "paper"},
                    "time": 1234567890000,
                }
            ]
        }

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["processed"], 1)
        self.assertEqual(response.data["skipped"], 0)

    @patch("analytics.services.event_processor.EventProcessor.should_process_event")
    def test_webhook_skips_irrelevant_events(self, mock_should_process):
        """Test that the webhook skips irrelevant events."""
        mock_should_process.return_value = False

        payload = {
            "events": [
                {
                    "event_type": "page_view",  # Not ML-relevant
                    "user_id": str(self.user.id),
                    "time": 1234567890000,
                }
            ]
        }

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["processed"], 0)
        self.assertEqual(response.data["skipped"], 1)

    @patch("analytics.services.event_processor.EventProcessor.process_event")
    def test_webhook_handles_multiple_events(self, mock_process):
        """Test that the webhook handles multiple events in one payload."""
        payload = {
            "events": [
                {
                    "event_type": "click",
                    "user_id": str(self.user.id),
                    "event_properties": {"item_id": "doc_1"},
                    "time": 1234567890000,
                },
                {
                    "event_type": "upvote",
                    "user_id": str(self.user.id),
                    "event_properties": {"item_id": "doc_2"},
                    "time": 1234567891000,
                },
            ]
        }

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_process.call_count, 2)

    @patch("analytics.services.event_processor.EventProcessor.process_event")
    def test_webhook_continues_on_individual_error(self, mock_process):
        """Test that the webhook continues processing even if one event fails."""
        mock_process.side_effect = [Exception("Test error"), None]

        payload = {
            "events": [
                {
                    "event_type": "click",
                    "user_id": str(self.user.id),
                    "event_properties": {"item_id": "doc_1"},
                    "time": 1234567890000,
                },
                {
                    "event_type": "upvote",
                    "user_id": str(self.user.id),
                    "event_properties": {"item_id": "doc_2"},
                    "time": 1234567891000,
                },
            ]
        }

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        # Should still return 200 OK and process what it can
        self.assertEqual(response.status_code, status.HTTP_200_OK)
