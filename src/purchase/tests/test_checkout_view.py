from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from user.tests.helpers import create_user


class CheckoutSessionViewTest(APITestCase):
    def setUp(self):
        self.url = reverse("payment_view")
        self.user = create_user()

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_success(self, mock_stripe_session_create):
        # Arrange
        mock_stripe_session_create.return_value = {
            "id": "sessionId1",
            "url": "https://checkout.stripe.com/session/sessionId1",
        }

        paper = Paper.objects.create(title="title1")

        data = {
            "paper": paper.id,
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

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_missing_mandatory_parameter(
        self, mock_stripe_session_create
    ):
        # Arrange
        data = {
            # paper is missing!
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
                "paper": ["This field is required."],
            },
        )
        mock_stripe_session_create.assert_not_called()

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_error(self, mock_stripe_session_create):
        # Arrange
        mock_stripe_session_create.side_effect = Exception("Stripe error")

        paper = Paper.objects.create(title="title1")

        data = {
            "paper": paper.id,
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
