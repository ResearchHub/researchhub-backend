import logging
from decimal import Decimal
from typing import Any, Dict, Optional

import stripe
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.payment_model import (
    Payment,
    PaymentProcessor,
    PaymentPurpose,
)
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.rsc_purchase_fee import RscPurchaseFee
from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor
from reputation.utils import calculate_rsc_purchase_fees

logger = logging.getLogger(__name__)

# The amount for Article Processing Charge (APC) in cents
APC_AMOUNT_CENTS = 0  # $0 - Zero cost transaction


class PaymentService:
    """Service for handling payment-related business logic."""

    def create_checkout_session(
        self,
        user_id: int,
        purpose: str,
        amount: Optional[int] = None,
        paper_id: Optional[int] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe checkout session.

        Args:
            user_id: ID of the user making the payment.
            purpose: Purpose of the payment.
            amount: Amount to charge (optional for APC).
            paper_id: ID of the paper (required for APC).
            success_url: URL to redirect to after successful payment.
            cancel_url: URL to redirect to after cancelled payment.

        Returns:
            Dict containing session ID and URL
        """
        product_name = self.get_name_for_purpose(purpose)
        unit_amount = APC_AMOUNT_CENTS if purpose == PaymentPurpose.APC else amount

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": product_name,
                            },
                            "unit_amount": unit_amount,
                        },
                        "quantity": 1,
                    },
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user_id),
                    "purpose": purpose,
                    **(
                        # Include paper_id only if purpose is APC
                        {"paper_id": str(paper_id)}
                        if purpose == PaymentPurpose.APC and paper_id
                        else {}
                    ),
                },
            )

            return {
                "id": session.get("id"),
                "url": session.get("url"),
            }
        except Exception as e:
            logger.error("Error creating checkout session: %s", e)
            raise

    @transaction.atomic
    def _process_rsc_purchase(
        self, checkout_session: stripe.checkout.Session, user_id: int
    ) -> Payment:
        """
        Process an RSC purchase payment.

        Args:
            checkout_session: Stripe checkout session object
            user_id: ID of the user making the purchase

        Returns:
            Created Payment instance
        """
        # Create payment record
        payment = Payment.objects.create(
            amount=checkout_session["amount_total"],
            currency=checkout_session["currency"].upper(),
            external_payment_id=checkout_session["payment_intent"],
            payment_processor=PaymentProcessor.STRIPE,
            purpose=PaymentPurpose.RSC_PURCHASE,
            user_id=user_id,
            object_id=user_id,  # For RSC purchases, reference the user
            content_type=ContentType.objects.get(app_label="user", model="user"),
        )

        # Convert cents to dollars, then USD to RSC
        usd_amount = checkout_session["amount_total"] / 100
        rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)

        # Create a purchase distribution
        purchase_distribution = create_purchase_distribution(
            user=payment.user, amount=rsc_amount
        )

        # Use distributor to create locked balance
        distributor = Distributor(
            distribution=purchase_distribution,
            recipient=payment.user,
            db_record=payment,
            timestamp=timezone.now().timestamp(),
            giver=None,  # Platform gives the RSC
        )
        distributor.distribute_locked_balance(lock_type=Balance.LockType.RSC_PURCHASE)

        return payment

    def insert_payment_from_checkout_session(
        self, checkout_session: stripe.checkout.Session
    ) -> Payment:
        """
        Create a Payment record from a Stripe checkout session.

        Args:
            checkout_session: Stripe checkout session object

        Returns:
            Created Payment instance

        Raises:
            ValueError: If required metadata is missing
        """
        if "user_id" not in checkout_session["metadata"]:
            raise ValueError("Missing user_id in Stripe metadata")

        user_id = checkout_session["metadata"]["user_id"]
        purpose = checkout_session["metadata"].get("purpose", PaymentPurpose.APC)

        if purpose == PaymentPurpose.RSC_PURCHASE:
            return self._process_rsc_purchase(checkout_session, int(user_id))

        elif purpose == PaymentPurpose.APC:
            # Handle APC
            if "paper_id" not in checkout_session["metadata"]:
                raise ValueError("Missing paper_id in Stripe metadata")

            paper_id = checkout_session["metadata"]["paper_id"]

            return Payment.objects.create(
                amount=checkout_session["amount_total"],
                currency=checkout_session["currency"].upper(),
                external_payment_id=checkout_session["payment_intent"],
                payment_processor=PaymentProcessor.STRIPE,
                purpose=purpose,
                object_id=paper_id,
                content_type=ContentType.objects.get_for_model(Paper),
                user_id=int(user_id),
            )

        else:
            raise ValueError(f"Unknown payment purpose: {purpose}")

    def get_name_for_purpose(self, purpose: str) -> str:
        """
        Get the display name for a payment purpose.

        Args:
            purpose: Payment purpose

        Returns:
            Display name for the purpose
        """
        if purpose == PaymentPurpose.APC:
            return "Article Processing Charge"
        elif purpose == PaymentPurpose.RSC_PURCHASE:
            return "ResearchCoin (RSC) Purchase"
        else:
            return "Unknown Purpose"

    def create_payment_intent(
        self,
        user_id: int,
        amount: int,
        currency: str = USD,
    ) -> Dict[str, Any]:
        """
        Create a Stripe payment intent for RSC purchase.

        Args:
            user_id: ID of the user making the payment.
            amount: Amount to charge (in cents if USD, in RSC if currency is RSC).
            currency: Currency for the payment (default: USD, can be RSC).

        Returns:
            Dict containing client_secret, payment_intent_id, and locked_rsc_amount
        """
        try:
            # Handle RSC currency conversion
            if currency == RSC:
                # Convert RSC amount to USD using current exchange rate
                usd_amount = RscExchangeRate.rsc_to_usd(amount)
                # Add platform fees to the Stripe amount
                fees, rh_fee, dao_fee, current_fee_obj = calculate_rsc_purchase_fees(
                    Decimal(str(usd_amount))
                )
                stripe_amount = int(
                    (Decimal(str(usd_amount)) + fees) * 100
                )  # Convert to cents for Stripe
                locked_rsc_amount = amount  # Store the original RSC amount (no fees)
            else:
                # USD amount (in cents)
                usd_amount = amount / 100
                # Add platform fees to the Stripe amount
                fees, rh_fee, dao_fee, current_fee_obj = calculate_rsc_purchase_fees(
                    Decimal(str(usd_amount))
                )
                stripe_amount = int(
                    (Decimal(str(usd_amount)) + fees) * 100
                )  # Convert to cents for Stripe
                # Convert USD to RSC for metadata (will use current rate at confirmation time)
                locked_rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)

            payment_intent = stripe.PaymentIntent.create(
                amount=stripe_amount,
                currency="usd",
                metadata={
                    "user_id": str(user_id),
                    "purpose": PaymentPurpose.RSC_PURCHASE,
                    "locked_rsc_amount": str(locked_rsc_amount),
                    "original_currency": currency.lower(),
                    "original_amount": str(amount),
                    "platform_fees": str(fees),
                },
                automatic_payment_methods={"enabled": True},
            )

            return {
                "client_secret": payment_intent.client_secret,
                "payment_intent_id": payment_intent.id,
                "locked_rsc_amount": locked_rsc_amount,
                "stripe_amount_cents": stripe_amount,
            }
        except Exception as e:
            logger.error("Error creating payment intent: %s", e)
            raise

    def process_payment_intent_confirmation(self, payment_intent_id: str) -> Payment:
        """
        Process a confirmed payment intent and create a Payment record for RSC purchase.

        Args:
            payment_intent_id: ID of the confirmed payment intent

        Returns:
            Created Payment instance
        """
        try:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

            if payment_intent.status != "succeeded":
                raise ValueError(f"Payment intent {payment_intent_id} is not succeeded")

            user_id = int(payment_intent.metadata.get("user_id"))
            purpose = payment_intent.metadata.get(
                "purpose", PaymentPurpose.RSC_PURCHASE
            )

            if purpose != PaymentPurpose.RSC_PURCHASE:
                raise ValueError(f"Unexpected payment purpose: {purpose}")

            # Get the locked RSC amount from metadata
            locked_rsc_amount = float(
                payment_intent.metadata.get("locked_rsc_amount", 0)
            )

            # Create payment record
            payment = Payment.objects.create(
                amount=payment_intent.amount,
                currency=payment_intent.currency.upper(),
                external_payment_id=payment_intent.id,
                payment_processor=PaymentProcessor.STRIPE,
                purpose=purpose,
                user_id=user_id,
                object_id=user_id,
                content_type=ContentType.objects.get(app_label="user", model="user"),
            )

            # Create fee records
            platform_fees = float(payment_intent.metadata.get("platform_fees", 0))

            # Always create balance record for the main payment
            Balance.objects.create(
                user=payment.user,
                content_type=ContentType.objects.get_for_model(Payment),
                object_id=payment.id,
                amount=f"-{payment.amount}",
            )

            # Create balance record for fees only if they exist
            if platform_fees > 0:
                current_fee = RscPurchaseFee.objects.last()

                # Create balance record for fees
                Balance.objects.create(
                    user=payment.user,
                    content_type=ContentType.objects.get_for_model(RscPurchaseFee),
                    object_id=current_fee.id,
                    amount=f"-{platform_fees}",
                )

            # Use the locked RSC amount from metadata
            if locked_rsc_amount > 0:
                rsc_amount = locked_rsc_amount
            else:
                # Fallback: convert USD to RSC using current rate
                usd_amount = payment_intent.amount / 100
                rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)

            # Create a purchase distribution
            purchase_distribution = create_purchase_distribution(
                user=payment.user, amount=rsc_amount
            )

            # Use distributor to create locked balance
            distributor = Distributor(
                distribution=purchase_distribution,
                recipient=payment.user,
                db_record=payment,
                timestamp=timezone.now().timestamp(),
                giver=None,
            )
            distributor.distribute_locked_balance(
                lock_type=Balance.LockType.RSC_PURCHASE
            )

            return payment

        except Exception as e:
            logger.error("Error processing payment intent confirmation: %s", e)
            raise
