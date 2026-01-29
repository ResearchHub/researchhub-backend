import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import stripe
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from purchase.related_models.constants.currency import RSC
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.payment_model import (
    Payment,
    PaymentProcessor,
    PaymentPurpose,
)
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor
from reputation.utils import calculate_rsc_purchase_fees
from user.models import User

logger = logging.getLogger(__name__)

# The amount for Article Processing Charge (APC) in cents
APC_AMOUNT_CENTS = 0  # $0 - Zero cost transaction

# Stripe fee structure (as of 2024)
STRIPE_FEE_PERCENT = Decimal("0.029")  # 2.9%
STRIPE_FEE_FIXED_CENTS = 30  # $0.30


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
        rsc_amount: Decimal,
        fundraise_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe payment intent for RSC purchase.

        Args:
            user_id: ID of the user making the payment.
            rsc_amount: Amount of RSC to purchase (Decimal for precision).
            fundraise_id: Optional fundraise ID to auto-contribute to after purchase.

        Returns:
            Dict containing client_secret, payment_intent_id, and locked_rsc_amount
        """
        try:
            # Convert RSC amount to USD using current exchange rate
            usd_amount = RscExchangeRate.rsc_to_usd(rsc_amount)

            # Calculate platform fees in RSC (2% of RSC amount)
            rsc_fees, rh_fee, dao_fee, current_fee_obj = calculate_rsc_purchase_fees(
                Decimal(str(rsc_amount))
            )

            # Calculate platform fees in USD (for Stripe charge calculation)
            usd_fees, _, _, _ = calculate_rsc_purchase_fees(Decimal(str(usd_amount)))

            # Calculate Stripe fees (2.9% + $0.30)
            stripe_fee = (Decimal(str(usd_amount)) * STRIPE_FEE_PERCENT) + (
                Decimal(STRIPE_FEE_FIXED_CENTS) / 100
            )

            # Total amount = base + platform fees (USD) + Stripe fees
            total_fees = usd_fees + stripe_fee
            stripe_amount = int(
                (Decimal(str(usd_amount)) + total_fees) * 100
            )  # Convert to cents for Stripe

            metadata = {
                "user_id": str(user_id),
                "purpose": PaymentPurpose.RSC_PURCHASE,
                "locked_rsc_amount": str(rsc_amount),
                "original_currency": RSC.lower(),
                "original_amount": str(rsc_amount),
                "platform_fees_rsc": str(rsc_fees),
                "stripe_fees": str(stripe_fee),
            }

            # Add fundraise_id to metadata if provided
            if fundraise_id is not None:
                metadata["fundraise_id"] = str(fundraise_id)

            payment_intent = stripe.PaymentIntent.create(
                amount=stripe_amount,
                currency="usd",
                metadata=metadata,
                automatic_payment_methods={"enabled": True},
            )

            return {
                "client_secret": payment_intent.client_secret,
                "payment_intent_id": payment_intent.id,
                "locked_rsc_amount": rsc_amount,
                "stripe_amount_cents": stripe_amount,
            }
        except Exception as e:
            logger.error("Error creating payment intent: %s", e)
            raise

    def process_payment_intent_confirmation(
        self, payment_intent_id: str
    ) -> Tuple[Payment, Optional[Purchase]]:
        """
        Process a confirmed payment intent and create a Payment record for RSC purchase.

        If a fundraise_id is present in the payment intent metadata, the purchased RSC
        will be automatically contributed to the fundraise in a separate transaction.

        Args:
            payment_intent_id: ID of the confirmed payment intent

        Returns:
            Tuple of (Payment, Purchase or None). Purchase is returned if a fundraise
            contribution was created, otherwise None.
        """
        # Import here to avoid circular imports
        from purchase.services.fundraise_service import FundraiseService

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
            locked_rsc_amount = Decimal(
                payment_intent.metadata.get("locked_rsc_amount", "0")
            )

            # Get platform fees from metadata (for fundraise contribution calculation)
            platform_fees_rsc = Decimal(
                payment_intent.metadata.get("platform_fees_rsc", "0")
            )

            # Process payment and credit balance in its own atomic transaction
            payment, rsc_amount = self._create_payment_and_credit_balance(
                payment_intent=payment_intent,
                user_id=user_id,
                purpose=purpose,
                locked_rsc_amount=locked_rsc_amount,
            )

            # Handle fundraise contribution in a separate transaction
            # This ensures payment succeeds even if contribution fails
            fundraise_contribution = None
            fundraise_id_str = payment_intent.metadata.get("fundraise_id")

            if fundraise_id_str:
                fundraise_contribution = self._process_fundraise_contribution(
                    fundraise_id_str=fundraise_id_str,
                    user_id=user_id,
                    rsc_amount=rsc_amount,
                    platform_fees_rsc=platform_fees_rsc,
                    payment_id=payment.id,
                    fundraise_service=FundraiseService(),
                )

            return payment, fundraise_contribution

        except Exception as e:
            logger.error("Error processing payment intent confirmation: %s", e)
            raise

    @transaction.atomic
    def _create_payment_and_credit_balance(
        self,
        payment_intent,
        user_id: int,
        purpose: str,
        locked_rsc_amount: Decimal,
    ) -> Tuple[Payment, Decimal]:
        """
        Create payment record and credit user's balance.
        This is an atomic operation - either both succeed or both fail.

        Returns:
            Tuple of (Payment, rsc_amount credited)
        """
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

        # Use the locked RSC amount from metadata
        if locked_rsc_amount > 0:
            rsc_amount = locked_rsc_amount
        else:
            # Fallback: convert USD to RSC using current rate
            usd_amount = payment_intent.amount / 100
            rsc_amount = Decimal(str(RscExchangeRate.usd_to_rsc(usd_amount)))

        # Create a purchase distribution and credit the user's locked balance
        purchase_distribution = create_purchase_distribution(
            user=payment.user, amount=float(rsc_amount)
        )
        distributor = Distributor(
            distribution=purchase_distribution,
            recipient=payment.user,
            db_record=payment,
            timestamp=timezone.now().timestamp(),
            giver=None,
        )
        distributor.distribute_locked_balance(lock_type=Balance.LockType.RSC_PURCHASE)

        return payment, rsc_amount

    def _process_fundraise_contribution(
        self,
        fundraise_id_str: str,
        user_id: int,
        rsc_amount: Decimal,
        platform_fees_rsc: Decimal,
        payment_id: int,
        fundraise_service,
    ) -> Optional[Purchase]:
        """
        Process fundraise contribution in a separate transaction.
        Failures here do not affect the payment processing.

        Returns:
            Purchase if contribution succeeded, None otherwise
        """
        fundraise_id = int(fundraise_id_str)
        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
            user = User.objects.get(id=user_id)

            # Only contribute if fundraise is still open
            if fundraise.status != Fundraise.OPEN or fundraise.is_expired():
                logger.warning(
                    "Fundraise %s is no longer open for contributions, "
                    "skipping auto-contribution for payment %s",
                    fundraise_id,
                    payment_id,
                )
                return None

            # Contribute the RSC amount minus platform fees
            contribution_amount = rsc_amount - platform_fees_rsc
            contribution, error = fundraise_service.create_rsc_contribution(
                user=user,
                fundraise=fundraise,
                amount=contribution_amount,
            )

            if error:
                logger.error(
                    "Failed to auto-contribute to fundraise %s: %s",
                    fundraise_id,
                    error,
                )
                return None

            logger.info(
                "Auto-contributed %s RSC to fundraise %s from payment %s",
                contribution_amount,
                fundraise_id,
                payment_id,
            )
            return contribution

        except Fundraise.DoesNotExist:
            logger.error(
                "Fundraise %s not found for auto-contribution from payment %s",
                fundraise_id,
                payment_id,
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error during fundraise contribution for payment %s: %s",
                payment_id,
                e,
            )
            return None
