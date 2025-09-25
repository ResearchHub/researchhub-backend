import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.serializers.payment_intent_serializer import PaymentIntentSerializer
from purchase.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


class PaymentIntentView(APIView):
    """
    View for creating Stripe payment intents for RSC purchase.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PaymentIntentSerializer

    def __init__(self, payment_service: PaymentService = None, **kwargs):
        super().__init__(**kwargs)
        self.payment_service = payment_service or PaymentService()

    def post(self, request, *args, **kwargs):
        user_id = request.user.id
        serializer = PaymentIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        amount = data.get("amount")

        try:
            payment_intent_data = self.payment_service.create_payment_intent(
                user_id=user_id,
                amount=amount,
                currency=data.get("currency", "usd"),
            )

            return Response(payment_intent_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error creating payment intent: %s", e)
            return Response({"message": "Failed to create payment intent"}, status=500)
