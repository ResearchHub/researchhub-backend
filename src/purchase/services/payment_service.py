import logging
from typing import Any, Dict, Optional

import stripe
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from analytics.tasks import track_revenue_event
from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from purchase.related_models.payment_model import (
    Payment,
    PaymentProcessor,
    PaymentPurpose,
)
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor

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

            payment = Payment.objects.create(
                amount=checkout_session["amount_total"],
                currency=checkout_session["currency"].upper(),
                external_payment_id=checkout_session["payment_intent"],
                payment_processor=PaymentProcessor.STRIPE,
                purpose=purpose,
                object_id=paper_id,
                content_type=ContentType.objects.get_for_model(Paper),
                user_id=int(user_id),
            )

            # Track revenue event for APC fee
            usd_amount = checkout_session["amount_total"] / 100
            track_revenue_event.apply_async(
                (
                    int(user_id),
                    "RHJ_APC_FEE",
                    "0",
                    f"{usd_amount:.2f}",
                    "OFF_CHAIN",
                    ContentType.objects.get_for_model(Paper).model,
                    str(paper_id),
                    {
                        "currency": checkout_session["currency"].upper(),
                        "payment_processor": "STRIPE",
                        "stripe_payment_intent": checkout_session["payment_intent"],
                        "checkout_session_id": checkout_session["id"],
                        "payment_id": payment.id,
                    },
                ),
                priority=1,
            )

            return payment

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
