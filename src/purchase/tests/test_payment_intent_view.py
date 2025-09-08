from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework.test import APITestCase

from purchase.related_models.constants.currency import RSC, USD
from user.tests.helpers import create_user


class PaymentIntentViewTest(APITestCase):
    def setUp(self):
        self.url = reverse("payment_intent_view")
        self.user = create_user()

    @patch("purchase.views.payment_intent_view.PaymentService")
    def test_create_payment_intent_usd_success(self, mock_payment_service_class):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_payment_intent.return_value = {
            "client_secret": "pi_secret_123",
            "payment_intent_id": "pi_123456",
            "locked_rsc_amount": 100.0,
            "stripe_amount_cents": 1000,
        }

        data = {
            "amount": 1000,  # $10.00
            "currency": USD,
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "client_secret": "pi_secret_123",
                "payment_intent_id": "pi_123456",
                "locked_rsc_amount": 100.0,
                "stripe_amount_cents": 1000,
            },
        )

        # Verify the payment service was called correctly
        mock_payment_service.create_payment_intent.assert_called_once_with(
            user_id=self.user.id,
            amount=1000,
            currency=USD,
        )

    @patch("purchase.views.payment_intent_view.PaymentService")
    def test_create_payment_intent_rsc_success(self, mock_payment_service_class):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_payment_intent.return_value = {
            "client_secret": "pi_secret_456",
            "payment_intent_id": "pi_789012",
            "locked_rsc_amount": 100,
            "stripe_amount_cents": 500,
        }

        data = {
            "amount": 100,  # 100 RSC
            "currency": RSC,
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["locked_rsc_amount"], 100)
        self.assertEqual(response.data["stripe_amount_cents"], 500)

        # Verify the payment service was called correctly
        mock_payment_service.create_payment_intent.assert_called_once_with(
            user_id=self.user.id,
            amount=100,
            currency=RSC,
        )

    @patch("purchase.views.payment_intent_view.PaymentService")
    def test_create_payment_intent_default_currency(self, mock_payment_service_class):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_payment_intent.return_value = {
            "client_secret": "pi_secret_default",
            "payment_intent_id": "pi_default",
            "locked_rsc_amount": 50.0,
            "stripe_amount_cents": 500,
        }

        data = {
            "amount": 500,  # $5.00 (no currency specified, defaults to USD)
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)

        # Verify the payment service was called with default currency
        mock_payment_service.create_payment_intent.assert_called_once_with(
            user_id=self.user.id,
            amount=500,
            currency=USD,
        )

    def test_create_payment_intent_unauthenticated(self):
        # Arrange
        data = {
            "amount": 1000,
            "currency": USD,
        }

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_create_payment_intent_invalid_amount(self):
        # Arrange
        data = {
            "amount": 0,
            "currency": USD,
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.data)

    def test_create_payment_intent_invalid_currency(self):
        # Arrange
        data = {
            "amount": 1000,
            "currency": "invalid",
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("currency", response.data)

    @patch("purchase.views.payment_intent_view.PaymentService")
    def test_create_payment_intent_service_error(self, mock_payment_service_class):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_payment_intent.side_effect = Exception(
            "Stripe error"
        )

        data = {
            "amount": 1000,
            "currency": USD,
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["message"], "Failed to create payment intent")
