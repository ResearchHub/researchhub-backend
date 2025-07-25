from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
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

    @patch("stripe.checkout.Session.create")
    def test_create_rsc_purchase_checkout_session_success(
        self, mock_stripe_session_create
    ):
        # Arrange
        # Create exchange rate
        RscExchangeRate.objects.create(
            rate=Decimal("3.00"),
            real_rate=Decimal("3.00"),
            price_source="COIN_GECKO",
            target_currency="USD",
        )

        mock_stripe_session_create.return_value = {
            "id": "sessionId2",
            "url": "https://checkout.stripe.com/session/sessionId2",
        }

        data = {
            "purchase_type": "rsc_purchase",
            "usd_amount": "100.00",
            "success_url": "https://researchhub.com/rsc/success",
            "failure_url": "https://researchhub.com/rsc/cancel",
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], "sessionId2")
        self.assertEqual(
            response.data["url"], "https://checkout.stripe.com/session/sessionId2"
        )
        self.assertEqual(response.data["rsc_amount"], "33.33")  # 100 / 3 = 33.33

        # Verify Stripe session creation was called with correct parameters
        mock_stripe_session_create.assert_called_once()
        call_args = mock_stripe_session_create.call_args[1]

        # Check metadata
        self.assertEqual(call_args["metadata"]["purchase_type"], "rsc_purchase")
        self.assertEqual(call_args["metadata"]["usd_amount"], "100.00")
        self.assertEqual(call_args["metadata"]["rsc_amount"], "33.33")
        self.assertEqual(call_args["metadata"]["exchange_rate"], "3.0")

        # Check line items
        self.assertEqual(
            call_args["line_items"][0]["price_data"]["unit_amount"], 10000
        )  # $100 in cents
        self.assertIn(
            "ResearchCoin (RSC) Purchase",
            call_args["line_items"][0]["price_data"]["product_data"]["name"],
        )

    def test_create_rsc_purchase_checkout_invalid_amount(self):
        # Arrange
        RscExchangeRate.objects.create(
            rate=Decimal("3.00"),
            real_rate=Decimal("3.00"),
            price_source="COIN_GECKO",
            target_currency="USD",
        )

        data = {
            "purchase_type": "rsc_purchase",
            "usd_amount": "0.50",  # Below minimum
            "success_url": "https://researchhub.com/rsc/success",
            "failure_url": "https://researchhub.com/rsc/cancel",
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("Minimum purchase amount is $1.00", str(response.data))

    def test_create_rsc_purchase_checkout_missing_amount(self):
        # Arrange
        data = {
            "purchase_type": "rsc_purchase",
            # usd_amount is missing
            "success_url": "https://researchhub.com/rsc/success",
            "failure_url": "https://researchhub.com/rsc/cancel",
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("USD amount is required for RSC purchases", str(response.data))

    @patch("stripe.checkout.Session.create")
    def test_paper_apc_still_works_after_changes(self, mock_stripe_session_create):
        """Ensure original paper APC functionality still works"""
        # Arrange
        mock_stripe_session_create.return_value = {
            "id": "sessionId3",
            "url": "https://checkout.stripe.com/session/sessionId3",
        }

        paper = Paper.objects.create(title="Test Paper")

        data = {
            # purchase_type defaults to "paper_apc" when not provided
            "paper": paper.id,
            "success_url": "https://researchhub.com/success",
            "failure_url": "https://researchhub.com/failure",
        }

        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(self.url, data=data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], "sessionId3")
        self.assertEqual(
            response.data["url"], "https://checkout.stripe.com/session/sessionId3"
        )
        # Should NOT have rsc_amount in response for paper APC
        self.assertNotIn("rsc_amount", response.data)
