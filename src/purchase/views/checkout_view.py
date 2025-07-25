import logging

import stripe
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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

        purchase_type = data.get("purchase_type", "paper_apc")

        try:
            if purchase_type == "paper_apc":
                # Original paper APC fee logic
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price_data": {
                                "currency": "usd",
                                "product_data": {
                                    "name": "Paper APC Fee",
                                },
                                "unit_amount": 30000,
                            },
                            "quantity": 1,
                        },
                    ],
                    mode="payment",
                    success_url=data["success_url"],
                    cancel_url=data["failure_url"],
                    metadata={
                        "user_id": user_id,
                        "paper_id": data["paper"].id,
                    },
                )
            else:  # rsc_purchase
                # RSC purchase logic
                usd_amount = data["usd_amount"]
                rsc_amount = data["rsc_amount"]
                exchange_rate = data["exchange_rate"]

                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price_data": {
                                "currency": "usd",
                                "product_data": {
                                    "name": "ResearchCoin (RSC) Purchase",
                                    "description": f"{rsc_amount} RSC at ${exchange_rate}/RSC",
                                },
                                "unit_amount": int(
                                    usd_amount * 100
                                ),  # Convert to cents
                            },
                            "quantity": 1,
                        },
                    ],
                    mode="payment",
                    success_url=data["success_url"],
                    cancel_url=data["failure_url"],
                    metadata={
                        "user_id": str(user_id),
                        "purchase_type": "rsc_purchase",
                        "usd_amount": str(usd_amount),
                        "rsc_amount": str(rsc_amount),
                        "exchange_rate": str(exchange_rate),
                    },
                )

            response_data = {
                "id": session.get("id"),
                "url": session.get("url"),
            }

            # Add RSC amount to response for RSC purchases
            if purchase_type == "rsc_purchase":
                response_data["rsc_amount"] = str(data["rsc_amount"])

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error("Error creating checkout session: %s", e)
            return Response(
                {"message": "Failed to create checkout session"}, status=500
            )
