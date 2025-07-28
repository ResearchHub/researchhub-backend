from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from purchase.related_models.payment_model import PaymentPurpose
from purchase.views.checkout_view import CheckoutView
from user.tests.helpers import create_user


class CheckoutSessionViewTest(APITestCase):
    def setUp(self):
        self.url = reverse("payment_view")
        self.user = create_user()

    @patch("purchase.views.checkout_view.PaymentService")
    def test_create_checkout_session_success(self, mock_payment_service_class):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_checkout_session.return_value = {
            "id": "sessionId1",
            "url": "https://checkout.stripe.com/session/sessionId1",
        }

        paper = Paper.objects.create(title="title1")

        data = {
            "paper": paper.id,
            "purpose": PaymentPurpose.APC,
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

        # Verify the payment service was called correctly
        mock_payment_service.create_checkout_session.assert_called_once_with(
            user_id=self.user.id,
            purpose=PaymentPurpose.APC.value,
            amount=None,
            paper_id=paper.id,
            success_url="https://researchhub.com/success",
            cancel_url="https://researchhub.com/failure",
        )

    @patch("purchase.views.checkout_view.PaymentService")
    def test_create_checkout_session_missing_mandatory_parameter(
        self, mock_payment_service_class
    ):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service

        data = {
            # purpose is missing!
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
    def test_create_checkout_session_apc_without_paper(
        self, mock_payment_service_class
    ):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service

        data = {
            "purpose": PaymentPurpose.APC.value,
            "success_url": "https://researchhub.com/success",
            "failure_url": "https://researchhub.com/failure",
            # paper is missing for APC purpose!
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {
                "paper": ["Paper is required when purpose is APC."],
            },
        )
        mock_payment_service.create_checkout_session.assert_not_called()

    @patch("purchase.views.checkout_view.PaymentService")
    def test_create_checkout_session_error(self, mock_payment_service_class):
        # Arrange
        mock_payment_service = MagicMock()
        mock_payment_service_class.return_value = mock_payment_service
        mock_payment_service.create_checkout_session.side_effect = Exception(
            "Payment service error"
        )

        paper = Paper.objects.create(title="title1")

        data = {
            "paper": paper.id,
            "purpose": PaymentPurpose.APC,
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
