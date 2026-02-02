import logging

import stripe
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.amplitude import track_event
from purchase.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


class StripeWebhookView(APIView):
    """
    View for processing Stripe webhooks.

    This view handles incoming POST requests from Stripe.

    See: https://docs.stripe.com/webhooks
    """

    permission_classes = [AllowAny]

    def __init__(self, payment_service: PaymentService = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set attributes for Amplitude tracking
        self.basename = "stripe_webhook"
        self.action = "process"
        self.payment_service = payment_service or PaymentService()

    @track_event
    def post(self, request, *args, **kwargs):
        """
        Process incoming webhook from Stripe.
        """
        payload = request.body
        request_signature = request.headers.get("Stripe-Signature", None)
        webhook_secret = settings.STRIPE_WEBHOOK_SIGNING_SECRET

        try:
            event = stripe.Webhook.construct_event(
                payload, request_signature, webhook_secret
            )
        except ValueError as e:
            logger.warning(f"Failed to parse event: {e}")
            return Response(
                {"message": "Invalid payload"}, status=status.HTTP_400_BAD_REQUEST
            )
        except stripe.error.SignatureVerificationError as e:
            logger.warning(f"Failed to validate signature: {e}")
            return Response(
                {"message": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            event_type = event["type"]
            match event_type:
                case "checkout.session.completed":
                    checkout_session = event["data"]["object"]
                    self.payment_service.insert_payment_from_checkout_session(
                        checkout_session
                    )
                    logger.info(
                        "Completed checkout session ID=%s processed",
                        checkout_session["id"],
                    )
                case "payment_intent.succeeded":
                    payment_intent = event["data"]["object"]
                    logger.info("Payment intent ID=%s succeeded", payment_intent["id"])

                    # Process the payment intent and create purchase record
                    payment, fundraise_contribution = (
                        self.payment_service.process_payment_intent_confirmation(
                            payment_intent["id"]
                        )
                    )

                    logger.info(
                        "Payment record created successfully: ID=%s, Amount=%s, User=%s",
                        payment.id,
                        payment.amount,
                        payment.user_id,
                    )

                    if fundraise_contribution:
                        logger.info(
                            "Fundraise contribution created: ID=%s, Amount=%s",
                            fundraise_contribution.id,
                            fundraise_contribution.amount,
                        )
                case _:
                    logger.info("Unhandled event type: %s", event_type)
        except ValueError as e:
            logger.error(f"Invalid event data: {e}")
            return Response(
                {"message": "Invalid event data"}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error processing event: {e}")
            return Response(
                {"message": "Error processing event"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"message": "Webhook successfully processed"}, status=status.HTTP_200_OK
        )
