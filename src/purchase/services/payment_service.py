import logging
from typing import Any, Dict, Optional

import stripe
from django.contrib.contenttypes.models import ContentType

from paper.related_models.paper_model import Paper
from purchase.related_models.payment_model import (
    Payment,
    PaymentProcessor,
    PaymentPurpose,
)

logger = logging.getLogger(__name__)


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
        unit_amount = self.get_amount_for_purpose(purpose, amount)

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
        if "paper_id" not in checkout_session["metadata"]:
            raise ValueError("Missing paper_id in Stripe metadata")
        if "user_id" not in checkout_session["metadata"]:
            raise ValueError("Missing user_id in Stripe metadata")

        user_id = checkout_session["metadata"]["user_id"]
        paper_id = checkout_session["metadata"]["paper_id"]

        return Payment.objects.create(
            amount=checkout_session["amount_total"],
            currency=checkout_session["currency"].upper(),
            external_payment_id=checkout_session["payment_intent"],
            payment_processor=PaymentProcessor.STRIPE,
            object_id=paper_id,
            content_type=ContentType.objects.get_for_model(Paper),
            user_id=user_id,
        )

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

    def get_amount_for_purpose(self, purpose: str, amount: Optional[int] = None) -> int:
        """
        Get the amount for a payment purpose.

        Args:
            purpose: Payment purpose
            amount: Optional amount (used for non-APC payments)

        Returns:
            Amount in cents
        """
        if purpose == "APC":
            return 30000
        else:
            return amount if amount else 0
