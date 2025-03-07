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
        data = serializer.data

        try:
            # FIXME: Current data is for testing purposes only.
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": "Paper APC Fee",
                            },
                            "unit_amount": 0,
                        },
                        "quantity": 1,
                    },
                ],
                mode="payment",
                success_url=data["success_url"],
                cancel_url=data["failure_url"],
                metadata={
                    "user_id": user_id,
                    "paper_id": data["paper"],
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
