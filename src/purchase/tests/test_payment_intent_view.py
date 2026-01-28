from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework.test import APITestCase

from user.tests.helpers import create_user


class PaymentIntentViewTest(APITestCase):
    def setUp(self):
        self.url = reverse("payment_intent_view")
        self.user = create_user()

    @patch("purchase.views.payment_intent_view.PaymentService")
    def test_create_payment_intent_success(self, mock_payment_service_class):
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
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["locked_rsc_amount"], 100)
        self.assertEqual(response.data["stripe_amount_cents"], 500)

        # Verify the payment service was called correctly with Decimal
        mock_payment_service.create_payment_intent.assert_called_once_with(
            user_id=self.user.id,
            rsc_amount=Decimal("100"),
        )

    @patch("purchase.views.payment_intent_view.PaymentService")
    def test_create_payment_intent_with_float_amount(self, mock_payment_service_class):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_payment_intent.return_value = {
            "client_secret": "pi_secret_456",
            "payment_intent_id": "pi_789012",
            "locked_rsc_amount": 100.5,
            "stripe_amount_cents": 503,
        }

        data = {
            "amount": 100.5,  # 100.5 RSC (float)
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["locked_rsc_amount"], 100.5)
        self.assertEqual(response.data["stripe_amount_cents"], 503)

        # Verify the payment service was called correctly with Decimal
        mock_payment_service.create_payment_intent.assert_called_once_with(
            user_id=self.user.id,
            rsc_amount=Decimal("100.50"),
        )

    def test_create_payment_intent_unauthenticated(self):
        # Arrange
        data = {
            "amount": 1000,
        }

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_create_payment_intent_invalid_amount(self):
        # Arrange
        data = {
            "amount": 0,
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.data)

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
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["message"], "Failed to create payment intent")
