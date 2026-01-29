import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.models import Fundraise
from purchase.related_models.payment_model import Payment
from purchase.serializers.payment_intent_serializer import PaymentIntentSerializer
from purchase.services.fundraise_service import FundraiseService
from purchase.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


class PaymentIntentView(APIView):
    """
    View for creating and checking status of Stripe payment intents for RSC purchase.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PaymentIntentSerializer

    def __init__(
        self,
        payment_service: PaymentService = None,
        fundraise_service: FundraiseService = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.payment_service = payment_service or PaymentService()
        self.fundraise_service = fundraise_service or FundraiseService()

    def post(self, request, *args, **kwargs):
        user_id = request.user.id
        serializer = PaymentIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        rsc_amount = data.get("amount")
        fundraise_id = data.get("fundraise_id")

        # Validate fundraise if provided
        if fundraise_id is not None:
            try:
                fundraise = Fundraise.objects.get(id=fundraise_id)
            except Fundraise.DoesNotExist:
                return Response(
                    {"message": "Fundraise does not exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            is_valid, error = (
                self.fundraise_service.validate_fundraise_for_contribution(
                    fundraise, request.user
                )
            )
            if not is_valid:
                return Response(
                    {"message": error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            payment_intent_data = self.payment_service.create_payment_intent(
                user_id=user_id,
                rsc_amount=rsc_amount,
                fundraise_id=fundraise_id,
            )

            return Response(payment_intent_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error creating payment intent: %s", e)
            return Response({"message": "Failed to create payment intent"}, status=500)

    def get(self, request, payment_intent_id, *args, **kwargs):
        """
        Check if a payment intent has been processed and balance credited.

        Returns:
            {"status": "completed"} if payment was processed
            {"status": "pending"} if still waiting for webhook
        """
        payment = Payment.objects.filter(
            external_payment_id=payment_intent_id,
            user=request.user,
        ).first()

        if payment:
            return Response({"status": "completed"})

        return Response({"status": "pending"})
