from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework.test import APITestCase

from purchase.related_models.payment_model import (
    Payment,
    PaymentProcessor,
    PaymentPurpose,
)
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

        # Verify the payment service was called correctly
        mock_payment_service.create_payment_intent.assert_called_once_with(
            user_id=self.user.id,
            rsc_amount=100,
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


class PaymentIntentStatusViewTest(APITestCase):
    def setUp(self):
        self.user = create_user()
        self.payment_intent_id = "pi_test_123"
        self.url = reverse(
            "payment_intent_status_view",
            kwargs={"payment_intent_id": self.payment_intent_id},
        )

    def test_get_payment_intent_status_completed(self):
        # Arrange - Create a payment record
        Payment.objects.create(
            amount=1000,
            currency="USD",
            external_payment_id=self.payment_intent_id,
            payment_processor=PaymentProcessor.STRIPE,
            purpose=PaymentPurpose.RSC_PURCHASE,
            user=self.user,
            object_id=self.user.id,
            content_type=ContentType.objects.get(app_label="user", model="user"),
        )
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "completed")

    def test_get_payment_intent_status_pending(self):
        # Arrange - No payment record exists
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending")

    def test_get_payment_intent_status_unauthenticated(self):
        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_get_payment_intent_status_wrong_user(self):
        # Arrange - Payment belongs to a different user
        other_user = create_user(email="other@example.com")
        Payment.objects.create(
            amount=1000,
            currency="USD",
            external_payment_id=self.payment_intent_id,
            payment_processor=PaymentProcessor.STRIPE,
            purpose=PaymentPurpose.RSC_PURCHASE,
            user=other_user,
            object_id=other_user.id,
            content_type=ContentType.objects.get(app_label="user", model="user"),
        )
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(self.url)

        # Assert - Should return pending since payment doesn't belong to this user
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending")
