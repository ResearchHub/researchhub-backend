import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class AmplitudeWebhookTestCase(TestCase):
    """
    Test cases for the Amplitude webhook endpoint.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("amplitude_webhook")
        self.user = create_random_default_user("test_user")
        self.post = create_post(created_by=self.user)

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
        self.assertIn("Invalid event format", response.data["message"])

    def test_webhook_rejects_invalid_json(self):
        """Test that the webhook rejects invalid JSON."""
        response = self.client.post(
            self.url, data="invalid json", content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid JSON", response.data["message"])

    @patch("analytics.views.amplitude_webhook_view.process_amplitude_event")
    def test_webhook_queues_events(self, mock_task):
        """Test that the webhook queues multiple events for async processing."""
        event1 = {
            "event_type": "feed_item_clicked",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time_": 1234567890000,
        }
        event2 = {
            "event_type": "work_document_viewed",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.post.unified_document.id),
                    "content_type": "researchhubpost",
                    "id": str(self.post.id),
                },
            },
            "time_": 1234567891000,
        }
        payload = {"events": [event1, event2]}

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["queued"], 2)
        self.assertEqual(mock_task.delay.call_count, 2)
        mock_task.delay.assert_any_call(event1)
        mock_task.delay.assert_any_call(event2)
