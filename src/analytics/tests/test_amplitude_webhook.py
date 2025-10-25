import json

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
        self.assertIn("Invalid event format", response.data["message"])

    def test_webhook_rejects_invalid_json(self):
        """Test that the webhook rejects invalid JSON."""
        response = self.client.post(
            self.url, data="invalid json", content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid JSON", response.data["message"])

    def test_webhook_processes_single_event(self):
        """Test that the webhook processes a single event."""
        payload = {
            "event_type": "vote_action",
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work.unified_document_id": "doc_123",
                "related_work.content_type": "paper",
            },
            "time": 1234567890000,
        }

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["processed"], 1)

    def test_webhook_handles_multiple_events(self):
        """Test that the webhook handles multiple events in one payload."""
        payload = {
            "events": [
                {
                    "event_type": "vote_action",
                    "event_properties": {
                        "user_id": str(self.user.id),
                        "related_work.unified_document_id": "doc_1",
                        "related_work.content_type": "paper",
                    },
                    "time": 1234567890000,
                },
                {
                    "event_type": "comment_created",
                    "event_properties": {
                        "user_id": str(self.user.id),
                        "related_work.content_type": "paper",
                        "related_work.id": "123",
                    },
                    "time": 1234567891000,
                },
            ]
        }

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["processed"], 2)

    def test_webhook_continues_on_individual_error(self):
        """Test that the webhook continues processing even if one event fails."""
        payload = {
            "events": [
                {
                    "event_type": "vote_action",
                    "event_properties": {
                        "user_id": str(self.user.id),
                        "related_work.unified_document_id": "doc_1",
                        "related_work.content_type": "paper",
                    },
                    "time": 1234567890000,
                },
                {
                    "event_type": "comment_created",
                    "event_properties": {
                        "user_id": str(self.user.id),
                        "related_work.unified_document_id": "doc_2",
                        "related_work.content_type": "paper",
                    },
                    "time": 1234567891000,
                },
            ]
        }

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        # Should still return 200 OK and process what it can
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["processed"], 2)
