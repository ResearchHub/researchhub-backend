from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase

from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from purchase.related_models.constants.currency import USD
from purchase.related_models.payment_model import (
    Payment,
    PaymentProcessor,
    PaymentPurpose,
)
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.rsc_purchase_fee import RscPurchaseFee
from purchase.services.payment_service import APC_AMOUNT_CENTS, PaymentService
from reputation.related_models.distribution import Distribution
from user.tests.helpers import create_user


class PaymentServiceTest(TestCase):
    def setUp(self):
        cache.clear()
        self.service = PaymentService()
        # Create revenue accounts needed for fee deductions
        from user.models import User

        self.revenue_account = User.objects.create(
            email="revenue@researchhub.com", username="revenue_account"
        )
        self.dao_account = User.objects.create(
            email="revenue1@researchhub.foundation", username="dao_account"
        )
        self.user = create_user()
        self.paper = Paper.objects.create(title="Test Paper")
        # Create RscPurchaseFee with 2% platform fee
        RscPurchaseFee.objects.all().delete()
        RscPurchaseFee.objects.create(rh_pct=0.02, dao_pct=0.00)

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
    def test_create_payment_intent_success(self, mock_stripe_payment_intent_create):
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
                rsc_amount=100,  # 100 RSC
            )

        # Assert
        self.assertEqual(result["client_secret"], "pi_secret_456")
        self.assertEqual(result["payment_intent_id"], "pi_789012")
        self.assertEqual(result["locked_rsc_amount"], 100)
        # $5.00 + platform fee ($0.10) + Stripe fee ($0.445) = $5.545 = 554 cents
        self.assertEqual(result["stripe_amount_cents"], 554)

        # Verify Stripe was called with correct parameters
        mock_stripe_payment_intent_create.assert_called_once_with(
            amount=554,  # $5.00 + platform fee + Stripe fee
            currency="usd",
            metadata={
                "user_id": str(self.user.id),
                "purpose": PaymentPurpose.RSC_PURCHASE,
                "locked_rsc_amount": "100",
                "original_currency": "rsc",
                "original_amount": "100",
                "platform_fees_rsc": "2.00",  # 2% platform fee in RSC
                "stripe_fees": "0.4450",  # 2.9% + $0.30 Stripe fee
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
            payment, fundraise_contribution = (
                self.service.process_payment_intent_confirmation("pi_123456")
            )

        # Assert
        self.assertIsInstance(payment, Payment)
        self.assertIsNone(fundraise_contribution)
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

        # Mock distributor and fee deduction
        with (
            patch(
                "purchase.services.payment_service.create_purchase_distribution"
            ) as mock_create_dist,
            patch(
                "purchase.services.payment_service.Distributor"
            ) as mock_distributor_class,
            patch("purchase.services.payment_service.deduct_rsc_purchase_fees"),
        ):

            mock_distribution = MagicMock()
            mock_create_dist.return_value = mock_distribution

            mock_distributor = MagicMock()
            mock_distributor_class.return_value = mock_distributor

            # Act
            payment, fundraise_contribution = (
                self.service.process_payment_intent_confirmation("pi_123456")
            )

            # Assert
            self.assertIsInstance(payment, Payment)
            self.assertIsNone(fundraise_contribution)
            # Verify the gross amount (150.0 + 2% fee = 153.0) was used
            # This includes the fee for transparency before deduction
            mock_create_dist.assert_called_once()
            call_kwargs = mock_create_dist.call_args[1]
            self.assertEqual(call_kwargs["amount"], float(Decimal("153.0")))

    @patch("stripe.PaymentIntent.create")
    def test_create_payment_intent_includes_fees_in_metadata(
        self, mock_stripe_payment_intent_create
    ):
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.client_secret = "pi_secret_fees"
        mock_payment_intent.id = "pi_fees_123"
        mock_stripe_payment_intent_create.return_value = mock_payment_intent

        # Mock exchange rate and fee calculation
        # calculate_rsc_purchase_fees is called twice: once for RSC, once for USD
        with (
            patch.object(RscExchangeRate, "rsc_to_usd", return_value=5.0),
            patch(
                "purchase.services.payment_service.calculate_rsc_purchase_fees",
                side_effect=[
                    # First call: RSC fees (2% of 100 RSC = 2.0 RSC)
                    (Decimal("2.00"), Decimal("2.00"), Decimal("0.00"), None),
                    # Second call: USD fees (2% of $5 = $0.10)
                    (Decimal("0.10"), Decimal("0.10"), Decimal("0.00"), None),
                ],
            ),
        ):

            # Act
            result = self.service.create_payment_intent(
                user_id=self.user.id,
                rsc_amount=100,  # 100 RSC
            )

        # Assert
        # $5.00 + $0.10 platform fee + $0.445 Stripe fee = $5.545 = 554 cents
        self.assertEqual(result["stripe_amount_cents"], 554)

        # Verify Stripe was called with fees in metadata
        mock_stripe_payment_intent_create.assert_called_once_with(
            amount=554,
            currency="usd",
            metadata={
                "user_id": str(self.user.id),
                "purpose": PaymentPurpose.RSC_PURCHASE,
                "locked_rsc_amount": "100",
                "original_currency": "rsc",
                "original_amount": "100",
                "platform_fees_rsc": "2.00",
                "stripe_fees": "0.4450",
            },
            automatic_payment_methods={"enabled": True},
        )

    @patch("stripe.PaymentIntent.retrieve")
    def test_process_payment_intent_confirmation_creates_balance_records(
        self, mock_stripe_retrieve
    ):
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1079  # $10.79 with fees
        mock_payment_intent.currency = "usd"
        mock_payment_intent.id = "pi_balance_123"
        mock_payment_intent.metadata = {
            "user_id": str(self.user.id),
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "locked_rsc_amount": "100.0",
            "platform_fees_rsc": "2.0",
        }
        mock_stripe_retrieve.return_value = mock_payment_intent

        with (
            patch(
                "purchase.services.payment_service.create_purchase_distribution"
            ) as mock_create_dist,
            patch(
                "purchase.services.payment_service.Distributor"
            ) as mock_distributor_class,
            patch(
                "purchase.services.payment_service.deduct_rsc_purchase_fees"
            ) as mock_deduct_fees,
        ):

            mock_distribution = MagicMock()
            mock_create_dist.return_value = mock_distribution

            mock_distributor = MagicMock()
            mock_distributor_class.return_value = mock_distributor

            # Act
            payment, fundraise_contribution = (
                self.service.process_payment_intent_confirmation("pi_balance_123")
            )

            # Verify distributor was called with gross amount (rsc_amount + fee)
            mock_create_dist.assert_called_once()
            call_args = mock_create_dist.call_args
            # The amount should be 102.0 (100 + 2% fee)
            self.assertAlmostEqual(call_args[1]["amount"], 102.0, places=1)
            mock_distributor.distribute_locked_balance.assert_called_once_with(
                lock_type=Balance.LockType.RSC_PURCHASE
            )

            # Verify fee deduction was called
            mock_deduct_fees.assert_called_once()

        # Assert
        self.assertIsInstance(payment, Payment)
        self.assertIsNone(fundraise_contribution)

        # Verify fee balance record was created (for transparency)
        balance_records = Balance.objects.filter(user=payment.user)
        self.assertEqual(balance_records.count(), 1)
        fee_record = balance_records.first()
        self.assertTrue(fee_record.is_locked)
        self.assertEqual(float(fee_record.amount), -2.0)  # 2% of 100 RSC

    @patch("stripe.PaymentIntent.retrieve")
    def test_process_payment_intent_confirmation_with_fees(self, mock_stripe_retrieve):
        # Arrange - Test that fees are properly calculated and deducted
        mock_payment_intent = MagicMock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1000  # $10.00
        mock_payment_intent.currency = "usd"
        mock_payment_intent.id = "pi_fees_123"
        mock_payment_intent.metadata = {
            "user_id": str(self.user.id),
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "locked_rsc_amount": "100.0",
            "platform_fees_rsc": "2.00",  # 2% of 100
        }
        mock_stripe_retrieve.return_value = mock_payment_intent

        # Mock distributor but NOT fee functions to test real fee flow
        with (
            patch(
                "purchase.services.payment_service.create_purchase_distribution"
            ) as mock_create_dist,
            patch(
                "purchase.services.payment_service.Distributor"
            ) as mock_distributor_class,
            patch(
                "purchase.services.payment_service.deduct_rsc_purchase_fees"
            ) as mock_deduct_fees,
        ):

            mock_distribution = MagicMock()
            mock_create_dist.return_value = mock_distribution

            mock_distributor = MagicMock()
            mock_distributor_class.return_value = mock_distributor

            # Act
            payment, fundraise_contribution = (
                self.service.process_payment_intent_confirmation("pi_fees_123")
            )

            # Verify distributor was called with gross amount (100 + 2% = 102)
            mock_create_dist.assert_called_once()
            call_args = mock_create_dist.call_args
            self.assertAlmostEqual(call_args[1]["amount"], 102.0, places=1)
            mock_distributor.distribute_locked_balance.assert_called_once_with(
                lock_type=Balance.LockType.RSC_PURCHASE
            )

            # Verify fee deduction was called with correct amounts
            mock_deduct_fees.assert_called_once()
            fee_call_args = mock_deduct_fees.call_args[0]
            self.assertEqual(fee_call_args[0], payment.user)  # user
            self.assertAlmostEqual(float(fee_call_args[1]), 2.0, places=1)  # total fee

        # Assert
        self.assertIsInstance(payment, Payment)
        self.assertIsNone(fundraise_contribution)

        # Verify fee balance record was created for transparency
        balance_records = Balance.objects.filter(user=payment.user)
        self.assertEqual(balance_records.count(), 1)
        fee_record = balance_records.first()
        self.assertTrue(fee_record.is_locked)
        self.assertEqual(float(fee_record.amount), -2.0)  # 2% fee deducted

    @patch("stripe.PaymentIntent.retrieve")
    def test_process_payment_intent_confirmation_updates_user_balance(
        self, mock_stripe_retrieve
    ):
        """Integration test: verify user balance is updated after payment."""
        # Arrange
        locked_rsc_amount = 100.0
        mock_payment_intent = MagicMock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 1000  # $10.00
        mock_payment_intent.currency = "usd"
        mock_payment_intent.id = "pi_integration_123"
        mock_payment_intent.metadata = {
            "user_id": str(self.user.id),
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "locked_rsc_amount": str(locked_rsc_amount),
            "platform_fees_rsc": "0.00",
        }
        mock_stripe_retrieve.return_value = mock_payment_intent

        # Act - don't mock the Distributor so balance is actually created
        payment, fundraise_contribution = (
            self.service.process_payment_intent_confirmation("pi_integration_123")
        )

        # Assert
        self.assertIsInstance(payment, Payment)
        self.assertIsNone(fundraise_contribution)

        # Refresh user from db and verify locked balance
        self.user.refresh_from_db()
        locked_balance = self.user.get_locked_balance(
            lock_type=Balance.LockType.RSC_PURCHASE
        )
        self.assertEqual(locked_balance, locked_rsc_amount)

    @patch("stripe.PaymentIntent.create")
    def test_create_payment_intent_with_fundraise_id(
        self, mock_stripe_payment_intent_create
    ):
        """Test that create_payment_intent includes fundraise_id in metadata."""
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.client_secret = "pi_secret_fundraise"
        mock_payment_intent.id = "pi_fundraise_123"
        mock_stripe_payment_intent_create.return_value = mock_payment_intent

        fundraise_id = 42

        # Mock exchange rate (100 RSC = $5.00)
        with patch.object(RscExchangeRate, "rsc_to_usd", return_value=5.0):
            # Act
            result = self.service.create_payment_intent(
                user_id=self.user.id,
                rsc_amount=Decimal("100"),
                fundraise_id=fundraise_id,
            )

        # Assert
        self.assertEqual(result["client_secret"], "pi_secret_fundraise")
        self.assertEqual(result["payment_intent_id"], "pi_fundraise_123")

        # Verify Stripe was called with fundraise_id in metadata
        call_kwargs = mock_stripe_payment_intent_create.call_args[1]
        self.assertEqual(call_kwargs["metadata"]["fundraise_id"], "42")

    @patch("stripe.PaymentIntent.create")
    def test_create_payment_intent_without_fundraise_id(
        self, mock_stripe_payment_intent_create
    ):
        """Test that create_payment_intent does not include fundraise_id when None."""
        # Arrange
        mock_payment_intent = MagicMock()
        mock_payment_intent.client_secret = "pi_secret_no_fundraise"
        mock_payment_intent.id = "pi_no_fundraise_123"
        mock_stripe_payment_intent_create.return_value = mock_payment_intent

        # Mock exchange rate (100 RSC = $5.00)
        with patch.object(RscExchangeRate, "rsc_to_usd", return_value=5.0):
            # Act
            result = self.service.create_payment_intent(
                user_id=self.user.id,
                rsc_amount=Decimal("100"),
                fundraise_id=None,
            )

        # Assert
        call_kwargs = mock_stripe_payment_intent_create.call_args[1]
        self.assertNotIn("fundraise_id", call_kwargs["metadata"])

    @patch("stripe.PaymentIntent.retrieve")
    def test_user_receives_full_rsc_amount_after_paying_fees(
        self, mock_stripe_retrieve
    ):
        """
        Integration test: User should receive the FULL RSC amount they requested.

        The fee structure is designed so users pay fees ON TOP of the RSC value:
        - User requests 100 RSC
        - User pays: $5.00 (RSC value) + $0.10 (2% platform fee) + Stripe fees
        - User should receive: 100 RSC (NOT 98 RSC)

        The platform fee was already collected as extra USD, so we should NOT
        deduct it again from the RSC balance.
        """
        # Arrange
        requested_rsc_amount = Decimal("100.0")
        platform_fee_rsc = Decimal("2.0")  # 2% of 100 RSC

        mock_payment_intent = MagicMock()
        mock_payment_intent.status = "succeeded"
        mock_payment_intent.amount = 554  # $5.54 (includes fees on top)
        mock_payment_intent.currency = "usd"
        mock_payment_intent.id = "pi_full_amount_test"
        mock_payment_intent.metadata = {
            "user_id": str(self.user.id),
            "purpose": PaymentPurpose.RSC_PURCHASE,
            "locked_rsc_amount": str(requested_rsc_amount),
            "platform_fees_rsc": str(platform_fee_rsc),
        }
        mock_stripe_retrieve.return_value = mock_payment_intent

        # Act
        payment, _ = self.service.process_payment_intent_confirmation(
            "pi_full_amount_test"
        )

        # Assert - User should have the FULL 100 RSC they requested
        self.user.refresh_from_db()
        total_balance = float(self.user.get_balance(include_locked=True))

        self.assertEqual(total_balance, float(requested_rsc_amount))
