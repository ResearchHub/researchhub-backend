import json
from unittest.mock import patch

import stripe
from django.test import TestCase
from django.urls import reverse
from rest_framework import status

from paper.related_models.paper_model import Paper
from purchase.related_models.payment_model import Payment
from user.related_models.user_model import User


class StripeWebhookTestCase(TestCase):
    def setUp(self):
        self.url = reverse("stripe_webhook")
        self.valid_signature = "valid-signature"

    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_checkout_session_completed(self, mock_construct_event):
        # Arrange
        paper = Paper.objects.create()
        user = User.objects.create()

        event_data = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "id1",
                    "amount_total": 1000,
                    "currency": "usd",
                    "payment_intent": "paymentIntentId1",
                    "metadata": {
                        "paper_id": paper.id,
                        "user_id": user.id,
                    },
                },
            },
        }
        mock_construct_event.return_value = event_data

        # Act
        response = self.client.post(
            self.url,
            data=json.dumps(event_data),
            content_type="application/json",
            headers={"Stripe-Signature": self.valid_signature},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"message": "Webhook successfully processed"})

        payment = Payment.objects.get(external_payment_id="paymentIntentId1")
        self.assertIsNotNone(payment)

    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_checkout_session_missing_metadata(self, mock_construct_event):
        # Arrange
        user = User.objects.create()

        event_data = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "id1",
                    "amount_total": 1000,
                    "currency": "usd",
                    "payment_intent": "paymentIntentId1",
                    "metadata": {
                        # paper_id is missing!
                        "user_id": user.id,
                    },
                },
            },
        }
        mock_construct_event.return_value = event_data

        # Act
        response = self.client.post(
            self.url,
            data=json.dumps(event_data),
            content_type="application/json",
            headers={"Stripe-Signature": self.valid_signature},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_payment_intent_succeeded(self, mock_construct_event):
        # Arrange
        event_data = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "paymentIntentId1",
                    "amount": 1000,
                },
            },
        }
        mock_construct_event.return_value = event_data

        # Act
        response = self.client.post(
            self.url,
            data=json.dumps(event_data),
            content_type="application/json",
            headers={"Stripe-Signature": self.valid_signature},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"message": "Webhook successfully processed"})

    @patch("stripe.Webhook.construct_event")
    def test_webhooks_fails_with_invalid_signature(self, mock_construct_event):
        # Arrange
        mock_construct_event.side_effect = stripe.error.SignatureVerificationError(
            "Invalid signature", "invalid-signature"
        )

        event_data = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "paymentIntentId1",
                    "amount": 1000,
                },
            },
        }

        # Act
        response = self.client.post(
            self.url,
            data=json.dumps(event_data),
            content_type="application/json",
            headers={"Stripe-Signature": "invalid-signature"},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"message": "Invalid signature"})

    @patch("stripe.Webhook.construct_event")
    def test_webhook_fails_with_value_error(self, mock_construct_event):
        # Arrange
        mock_construct_event.side_effect = ValueError("Invalid payload")

        event_data = "INVALID PAYLOAD"

        # Act
        response = self.client.post(
            self.url,
            data=event_data,
            content_type="application/json",
            headers={"Stripe-Signature": self.valid_signature},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"message": "Invalid payload"})
