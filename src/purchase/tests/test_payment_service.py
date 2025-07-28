from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase

from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from purchase.related_models.payment_model import (
    Payment,
    PaymentProcessor,
    PaymentPurpose,
)
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.services.payment_service import APC_AMOUNT_CENTS, PaymentService
from reputation.related_models.distribution import Distribution
from user.tests.helpers import create_user


class PaymentServiceTest(TestCase):
    def setUp(self):
        cache.clear()
        self.service = PaymentService()
        self.user = create_user()
        self.paper = Paper.objects.create(title="Test Paper")

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_apc_success(self, mock_stripe_session_create):
        # Arrange
        mock_stripe_session_create.return_value = {
            "id": "sessionId1",
            "url": "https://checkout.stripe.com/session/sessionId1",
        }

        # Act
        result = self.service.create_checkout_session(
            user_id=self.user.id,
            purpose=PaymentPurpose.APC,
            paper_id=self.paper.id,
            success_url="https://researchhub.com/success",
            cancel_url="https://researchhub.com/failure",
        )

        # Assert
        self.assertEqual(result["id"], "sessionId1")
        self.assertEqual(
            result["url"], "https://checkout.stripe.com/session/sessionId1"
        )

        # Verify Stripe was called with correct parameters
        mock_stripe_session_create.assert_called_once_with(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": "Article Processing Charge",
                        },
                        "unit_amount": APC_AMOUNT_CENTS,
                    },
                    "quantity": 1,
                },
            ],
            mode="payment",
            success_url="https://researchhub.com/success",
            cancel_url="https://researchhub.com/failure",
            metadata={
                "user_id": str(self.user.id),
                "purpose": PaymentPurpose.APC,
                "paper_id": str(self.paper.id),
            },
        )

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_rsc_purchase_success(
        self, mock_stripe_session_create
    ):
        # Arrange
        mock_stripe_session_create.return_value = {
            "id": "sessionId2",
            "url": "https://checkout.stripe.com/session/sessionId2",
        }

        # Act
        result = self.service.create_checkout_session(
            user_id=self.user.id,
            purpose=PaymentPurpose.RSC_PURCHASE,
            amount=50000,
            success_url="https://researchhub.com/success",
            cancel_url="https://researchhub.com/failure",
        )

        # Assert
        self.assertEqual(result["id"], "sessionId2")
        self.assertEqual(
            result["url"], "https://checkout.stripe.com/session/sessionId2"
        )

        # Verify Stripe was called with correct parameters
        mock_stripe_session_create.assert_called_once_with(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": "ResearchCoin (RSC) Purchase",
                        },
                        "unit_amount": 50000,
                    },
                    "quantity": 1,
                },
            ],
            mode="payment",
            success_url="https://researchhub.com/success",
            cancel_url="https://researchhub.com/failure",
            metadata={
                "user_id": str(self.user.id),
                "purpose": PaymentPurpose.RSC_PURCHASE,
            },
        )

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_stripe_error(self, mock_stripe_session_create):
        # Arrange
        mock_stripe_session_create.side_effect = Exception("Stripe error")

        # Act & Assert
        with self.assertRaises(Exception) as context:
            self.service.create_checkout_session(
                user_id=self.user.id,
                purpose=PaymentPurpose.APC,
                paper_id=self.paper.id,
            )

        self.assertEqual(str(context.exception), "Stripe error")

    def test_insert_payment_from_checkout_session_success(self):
        # Arrange
        checkout_session = {
            "amount_total": APC_AMOUNT_CENTS,
            "currency": "usd",
            "payment_intent": "pi_123456",
            "metadata": {
                "user_id": str(self.user.id),
                "paper_id": str(self.paper.id),
            },
        }

        # Act
        payment = self.service.insert_payment_from_checkout_session(checkout_session)

        # Assert
        self.assertIsInstance(payment, Payment)
        self.assertEqual(payment.amount, APC_AMOUNT_CENTS)
        self.assertEqual(payment.currency, "USD")
        self.assertEqual(payment.external_payment_id, "pi_123456")
        self.assertEqual(payment.payment_processor, PaymentProcessor.STRIPE)
        self.assertEqual(payment.object_id, str(self.paper.id))
        self.assertEqual(payment.content_type, ContentType.objects.get_for_model(Paper))
        self.assertEqual(payment.user.id, self.user.id)

    def test_insert_payment_from_checkout_session_missing_paper_id(self):
        # Arrange
        checkout_session = {
            "amount_total": APC_AMOUNT_CENTS,
            "currency": "usd",
            "payment_intent": "pi_123456",
            "metadata": {
                "user_id": str(self.user.id),
                # paper_id is missing
            },
        }

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.service.insert_payment_from_checkout_session(checkout_session)

        self.assertEqual(str(context.exception), "Missing paper_id in Stripe metadata")

    def test_insert_payment_from_checkout_session_missing_user_id(self):
        # Arrange
        checkout_session = {
            "amount_total": APC_AMOUNT_CENTS,
            "currency": "usd",
            "payment_intent": "pi_123456",
            "metadata": {
                "paper_id": str(self.paper.id),
                # user_id is missing
            },
        }

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.service.insert_payment_from_checkout_session(checkout_session)

        self.assertEqual(str(context.exception), "Missing user_id in Stripe metadata")

    def test_insert_payment_from_checkout_session_rsc_purchase_success(self):
        # Arrange
        # Create an exchange rate: 1 RSC = $2.00
        RscExchangeRate.objects.create(
            rate=2.0,
            real_rate=2.0,
            target_currency="USD",
        )

        checkout_session = {
            "amount_total": 10000,  # $100.00
            "currency": "usd",
            "payment_intent": "pi_rsc_123456",
            "metadata": {
                "user_id": str(self.user.id),
                "purpose": PaymentPurpose.RSC_PURCHASE,
            },
        }

        # Act
        payment = self.service.insert_payment_from_checkout_session(checkout_session)

        # Debug: Check what distributions exist
        all_distributions = Distribution.objects.all()
        print(f"Total distributions: {all_distributions.count()}")
        for dist in all_distributions:
            print(
                f"Distribution: type={dist.distribution_type}, recipient={dist.recipient}, amount={dist.amount}"
            )

        # Assert payment was created correctly
        self.assertIsInstance(payment, Payment)
        self.assertEqual(payment.amount, 10000)
        self.assertEqual(payment.currency, "USD")
        self.assertEqual(payment.external_payment_id, "pi_rsc_123456")
        self.assertEqual(payment.payment_processor, PaymentProcessor.STRIPE)
        self.assertEqual(payment.purpose, PaymentPurpose.RSC_PURCHASE)
        self.assertEqual(payment.object_id, int(self.user.id))
        self.assertEqual(
            payment.content_type,
            ContentType.objects.get(app_label="user", model="user"),
        )
        self.assertEqual(payment.user.id, self.user.id)

        # Assert distribution was created
        distribution = Distribution.objects.get(
            recipient=self.user,
        )
        self.assertEqual(distribution.distribution_type, "PURCHASE")
        self.assertEqual(float(distribution.amount), 50.0)

        # Assert locked balance was created with proper conversion
        balance = Balance.objects.get(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Distribution),
            object_id=distribution.id,
        )
        self.assertEqual(balance.amount, "50.0")
        self.assertEqual(balance.user_id, self.user.id)
        self.assertTrue(balance.is_locked)
        self.assertEqual(balance.lock_type, Balance.LockType.RSC_PURCHASE)

    def test_get_name_for_purpose(self):
        # Test APC
        self.assertEqual(
            self.service.get_name_for_purpose(PaymentPurpose.APC),
            "Article Processing Charge",
        )

        # Test RSC Purchase
        self.assertEqual(
            self.service.get_name_for_purpose(PaymentPurpose.RSC_PURCHASE),
            "ResearchCoin (RSC) Purchase",
        )

        # Test unknown purpose
        self.assertEqual(
            self.service.get_name_for_purpose("UNKNOWN"), "Unknown Purpose"
        )
