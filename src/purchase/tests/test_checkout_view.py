from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework.test import APITestCase

from purchase.related_models.payment_model import PaymentPurpose
from user.tests.helpers import create_user


class CheckoutSessionViewTest(APITestCase):
    def setUp(self):
        self.url = reverse("payment_view")
        self.user = create_user()

    @patch("purchase.views.checkout_view.PaymentService")
    def test_creates_rsc_checkout_session(
        self, mock_payment_service_class: MagicMock
    ) -> None:
        """A valid RSC purchase creates a checkout session."""
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_checkout_session.return_value = {
            "id": "sessionId1",
            "url": "https://checkout.stripe.com/session/sessionId1",
        }
        data = {
            "amount": 100,
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "success_url": "https://researchhub.com/success",
            "failure_url": "https://researchhub.com/failure",
        }
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "id": "sessionId1",
                "url": "https://checkout.stripe.com/session/sessionId1",
            },
        )
        mock_payment_service.create_checkout_session.assert_called_once_with(
            user_id=self.user.id,
            purpose=PaymentPurpose.RSC_PURCHASE.value,
            amount=100,
            success_url="https://researchhub.com/success",
            cancel_url="https://researchhub.com/failure",
        )

    @patch("purchase.views.checkout_view.PaymentService")
    def test_rejects_checkout_without_purpose(
        self, mock_payment_service_class: MagicMock
    ) -> None:
        """A checkout request without a purpose is rejected."""
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        data = {
            "amount": 100,
            "success_url": "https://researchhub.com/success",
            "failure_url": "https://researchhub.com/failure",
        }
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {
                "purpose": ["This field is required."],
            },
        )
        mock_payment_service.create_checkout_session.assert_not_called()

    @patch("purchase.views.checkout_view.PaymentService")
    def test_returns_server_error_when_checkout_creation_fails(
        self, mock_payment_service_class: MagicMock
    ) -> None:
        """Payment service failures return a server error response."""
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_checkout_session.side_effect = Exception(
            "Payment service error"
        )
        data = {
            "amount": 100,
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "success_url": "https://researchhub.com/success",
            "failure_url": "https://researchhub.com/failure",
        }
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.data,
            {
                "message": "Failed to create checkout session",
            },
        )
