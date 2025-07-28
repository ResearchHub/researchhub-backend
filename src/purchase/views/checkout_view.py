import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.serializers.checkout_serializer import CheckoutSerializer
from purchase.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


class CheckoutView(APIView):
    """
    View for creating Stripe checkout sessions.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CheckoutSerializer

    def __init__(self, payment_service: PaymentService = None, **kwargs):
        super().__init__(**kwargs)
        self.payment_service = payment_service or PaymentService()

    def post(self, request, *args, **kwargs):
        user_id = request.user.id
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        amount = data.get("amount", None)
        paper_id = data.get("paper", None)
        purpose = data.get("purpose")

        try:
            session_data = self.payment_service.create_checkout_session(
                user_id=user_id,
                purpose=purpose,
                amount=amount,
                paper_id=paper_id,
                success_url=data.get("success_url", None),
                cancel_url=data.get("failure_url", None),
            )

            return Response(session_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error creating checkout session: %s", e)
            return Response(
                {"message": "Failed to create checkout session"}, status=500
            )
