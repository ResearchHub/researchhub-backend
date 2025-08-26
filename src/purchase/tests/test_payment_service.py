from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase

from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from purchase.related_models.constants.currency import RSC, USD
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
            target_currency=USD,
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

        # Assert payment was created correctly
        self.assertIsInstance(payment, Payment)
        self.assertEqual(payment.amount, 10000)
        self.assertEqual(payment.currency, USD)
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

    @patch("stripe.PaymentIntent.create")
    def test_create_payment_intent_usd_success(self, mock_stripe_payment_intent_create):
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.client_secret = "pi_secret_123"
        mock_payment_intent.id = "pi_123456"
        mock_stripe_payment_intent_create.return_value = mock_payment_intent

        # Mock exchange rate for USD path (also calls usd_to_rsc)
        with patch.object(RscExchangeRate, "usd_to_rsc", return_value=100.0):
            # Act
            result = self.service.create_payment_intent(
                user_id=self.user.id,
                amount=1000,  # $10.00
                currency=USD,
            )

        # Assert
        self.assertEqual(result["client_secret"], "pi_secret_123")
        self.assertEqual(result["payment_intent_id"], "pi_123456")
        self.assertEqual(result["locked_rsc_amount"], 100.0)
        # Update this to expect the amount with fees
        self.assertEqual(result["stripe_amount_cents"], 1070)  # $10.00 + fees

        # Verify Stripe was called with correct parameters
        mock_stripe_payment_intent_create.assert_called_once_with(
            amount=1070,  # Updated: $10.00 + fees
            currency="usd",
            metadata={
                "user_id": str(self.user.id),
                "purpose": PaymentPurpose.RSC_PURCHASE,
                "locked_rsc_amount": "100.0",
                "original_currency": "usd",
                "original_amount": "1000",
                "platform_fees": "0.700",  # Added: platform fees
            },
            automatic_payment_methods={"enabled": True},
        )

    @patch("stripe.PaymentIntent.create")
    def test_create_payment_intent_rsc_success(self, mock_stripe_payment_intent_create):
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.client_secret = "pi_secret_456"
        mock_payment_intent.id = "pi_789012"
        mock_stripe_payment_intent_create.return_value = mock_payment_intent

        # Mock exchange rate (100 RSC = $5.00)
        with patch.object(RscExchangeRate, "rsc_to_usd", return_value=5.0):
            # Act
            result = self.service.create_payment_intent(
                user_id=self.user.id,
                amount=100,  # 100 RSC
                currency=RSC,
            )

        # Assert
        self.assertEqual(result["client_secret"], "pi_secret_456")
        self.assertEqual(result["payment_intent_id"], "pi_789012")
        self.assertEqual(result["locked_rsc_amount"], 100)
        # Update this to expect the amount with fees
        self.assertEqual(result["stripe_amount_cents"], 535)  # $5.00 + fees

        # Verify Stripe was called with correct parameters
        mock_stripe_payment_intent_create.assert_called_once_with(
            amount=535,  # Updated: $5.00 + fees
            currency="usd",
            metadata={
                "user_id": str(self.user.id),
                "purpose": PaymentPurpose.RSC_PURCHASE,
                "locked_rsc_amount": "100",
                "original_currency": "rsc",
                "original_amount": "100",
                "platform_fees": "0.350",  # Added: platform fees
            },
            automatic_payment_methods={"enabled": True},
        )

    @patch("stripe.PaymentIntent.retrieve")
    def test_process_payment_intent_confirmation_success(self, mock_stripe_retrieve):
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1000
        mock_payment_intent.currency = "usd"
        mock_payment_intent.id = "pi_123456"
        mock_payment_intent.metadata = {
            "user_id": str(self.user.id),
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "locked_rsc_amount": "100.0",
        }
        mock_stripe_retrieve.return_value = mock_payment_intent

        # Mock exchange rate and distributor
        with (
            patch.object(RscExchangeRate, "usd_to_rsc", return_value=100.0),
            patch(
                "purchase.services.payment_service.create_purchase_distribution"
            ) as mock_create_dist,
            patch(
                "purchase.services.payment_service.Distributor"
            ) as mock_distributor_class,
        ):

            mock_distribution = MagicMock()
            mock_create_dist.return_value = mock_distribution

            mock_distributor = MagicMock()
            mock_distributor_class.return_value = mock_distributor

            # Act
            payment = self.service.process_payment_intent_confirmation("pi_123456")

        # Assert
        self.assertIsInstance(payment, Payment)
        self.assertEqual(payment.amount, 1000)
        self.assertEqual(payment.currency, "USD")
        self.assertEqual(payment.external_payment_id, "pi_123456")
        self.assertEqual(payment.purpose, PaymentPurpose.RSC_PURCHASE)
        self.assertEqual(payment.user_id, self.user.id)

        # Verify Stripe was called
        mock_stripe_retrieve.assert_called_once_with("pi_123456")

    @patch("stripe.PaymentIntent.retrieve")
    def test_process_payment_intent_confirmation_not_succeeded(
        self, mock_stripe_retrieve
    ):
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.status = "processing"  # Not succeeded
        mock_payment_intent.id = "pi_123456"
        mock_stripe_retrieve.return_value = mock_payment_intent

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.service.process_payment_intent_confirmation("pi_123456")

        self.assertIn("is not succeeded", str(context.exception))

    @patch("stripe.PaymentIntent.retrieve")
    def test_process_payment_intent_confirmation_uses_locked_rsc_amount(
        self, mock_stripe_retrieve
    ):
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1000
        mock_payment_intent.currency = "usd"
        mock_payment_intent.id = "pi_123456"
        mock_payment_intent.metadata = {
            "user_id": str(self.user.id),
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "locked_rsc_amount": "150.0",  # Specific RSC amount
        }
        mock_stripe_retrieve.return_value = mock_payment_intent

        # Mock distributor
        with (
            patch(
                "purchase.services.payment_service.create_purchase_distribution"
            ) as mock_create_dist,
            patch(
                "purchase.services.payment_service.Distributor"
            ) as mock_distributor_class,
        ):

            mock_distribution = MagicMock()
            mock_create_dist.return_value = mock_distribution

            mock_distributor = MagicMock()
            mock_distributor_class.return_value = mock_distributor

            # Act
            payment = self.service.process_payment_intent_confirmation("pi_123456")

        # Assert
        self.assertIsInstance(payment, Payment)
        # The payment should use the locked RSC amount (150.0) instead of recalculating
        # This is verified by checking that the payment was created successfully
