import logging

import stripe
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.related_models.payment_model import PaymentPurpose
from purchase.serializers.checkout_serializer import CheckoutSerializer

logger = logging.getLogger(__name__)


class CheckoutView(APIView):
    """
    View for creating Stripe checkout sessions.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CheckoutSerializer

    def post(self, request, *args, **kwargs):
        user_id = request.user.id
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        amount = data.get("amount", None)
        purpose = data.get("purpose")
        paper_id = data.get("paper", None)

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
                success_url=data.get("success_url", None),
                cancel_url=data.get("failure_url", None),
                metadata={
                    "user_id": user_id,
                    **(
                        # Include paper_id only if purpose is APC
                        {"paper_id": paper_id}
                        if purpose == PaymentPurpose.APC and paper_id
                        else {}
                    ),
                },
            )

            return Response(
                {
                    "id": session.get("id"),
                    "url": session.get("url"),
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error("Error creating checkout session: %s", e)
            return Response(
                {"message": "Failed to create checkout session"}, status=500
            )

    def get_name_for_purpose(self, purpose) -> str:
        """
        Helper method to get the name for the payment purpose.
        """
        if purpose == PaymentPurpose.APC:
            return "Article Processing Charge"
        elif purpose == PaymentPurpose.RSC_PURCHASE:
            return "ResearchCoin (RSC) Purchase"
        else:
            return "Unknown Purpose"

    def get_amount_for_purpose(self, purpose, amount) -> int:
        """
        Helper method to get the amount for the payment purpose.
        The amount is hard-coded for APC, while for other purposes,
        it uses the provided amount or defaults to 0.
        """
        if purpose == "APC":
            return 30000
        else:
            return amount if amount else 0
