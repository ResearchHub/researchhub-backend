import json
from unittest.mock import MagicMock, patch

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

    @patch("purchase.views.stripe_webhook_view.PaymentService")
    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_checkout_session_completed(
        self, mock_construct_event, mock_payment_service_class
    ):
        # Arrange
        paper = Paper.objects.create()
        user = User.objects.create()

        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service

        # Mock the payment creation
        mock_payment = Payment(
            id=1, amount=1000, currency="USD", external_payment_id="paymentIntentId1"
        )
        mock_payment_service.insert_payment_from_checkout_session.return_value = (
            mock_payment
        )

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

        # Verify the payment service was called
        mock_payment_service.insert_payment_from_checkout_session.assert_called_once_with(
            event_data["data"]["object"]
        )

    @patch("purchase.views.stripe_webhook_view.PaymentService")
    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_checkout_session_missing_metadata(
        self, mock_construct_event, mock_payment_service_class
    ):
        # Arrange
        user = User.objects.create()

        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.insert_payment_from_checkout_session.side_effect = (
            ValueError("Missing paper_id in Stripe metadata")
        )

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

    @patch("purchase.views.stripe_webhook_view.PaymentService")
    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_payment_intent_succeeded_success(
        self, mock_construct_event, mock_payment_service_class
    ):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service

        # Mock the payment creation
        mock_payment = Payment(
            id=1,
            amount=1000,
            currency="USD",
            external_payment_id="paymentIntentId1",
            user_id=1,
        )
        mock_payment_service.process_payment_intent_confirmation.return_value = (
            mock_payment
        )

        event_data = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "paymentIntentId1",
                    "amount": 1000,
                    "currency": "usd",
                    "metadata": {
                        "user_id": "1",
                        "purpose": "RSC_PURCHASE",
                        "locked_rsc_amount": "100.0",
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

        # Verify the payment service was called
        mock_payment_service.process_payment_intent_confirmation.assert_called_once_with(
            "paymentIntentId1"
        )

    @patch("purchase.views.stripe_webhook_view.PaymentService")
    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_payment_intent_succeeded_service_error(
        self, mock_construct_event, mock_payment_service_class
    ):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service

        # Mock the service to raise an exception
        mock_payment_service.process_payment_intent_confirmation.side_effect = (
            Exception("Payment processing failed")
        )

        event_data = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "paymentIntentId1",
                    "amount": 1000,
                    "currency": "usd",
                    "metadata": {
                        "user_id": "1",
                        "purpose": "RSC_PURCHASE",
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
        # Even if service fails, webhook should return 200 to avoid Stripe retries
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, {"message": "Error processing event"})

        # Verify the payment service was called
        mock_payment_service.process_payment_intent_confirmation.assert_called_once_with(
            "paymentIntentId1"
        )

    @patch("purchase.views.stripe_webhook_view.PaymentService")
    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_payment_intent_succeeded_missing_metadata(
        self, mock_construct_event, mock_payment_service_class
    ):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service

        # Mock the service to raise a ValueError for missing metadata
        mock_payment_service.process_payment_intent_confirmation.side_effect = (
            ValueError("Missing user_id in Stripe metadata")
        )

        event_data = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "paymentIntentId1",
                    "amount": 1000,
                    "currency": "usd",
                    "metadata": {
                        # user_id is missing!
                        "purpose": "RSC_PURCHASE",
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
        # Even if service fails, webhook should return 200 to avoid Stripe retries
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"message": "Invalid event data"})

        # Verify the payment service was called
        mock_payment_service.process_payment_intent_confirmation.assert_called_once_with(
            "paymentIntentId1"
        )

    @patch("purchase.views.stripe_webhook_view.PaymentService")
    @patch("stripe.Webhook.construct_event")
    def test_webhook_with_payment_intent_succeeded_creates_fee_records(
        self, mock_construct_event, mock_payment_service_class
    ):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service

        # Mock the payment creation with fee processing
        mock_payment = Payment(
            id=1,
            amount=1070,  # Amount with fees
            currency="USD",
            external_payment_id="paymentIntentWithFees",
            user_id=1,
        )
        mock_payment_service.process_payment_intent_confirmation.return_value = (
            mock_payment
        )

        event_data = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "paymentIntentWithFees",
                    "amount": 1070,
                    "currency": "usd",
                    "metadata": {
                        "user_id": "1",
                        "purpose": "RSC_PURCHASE",
                        "locked_rsc_amount": "100.0",
                        "platform_fees": "0.70",
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

        # Verify the payment service was called
        mock_payment_service.process_payment_intent_confirmation.assert_called_once_with(
            "paymentIntentWithFees"
        )
