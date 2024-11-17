import logging

import stripe
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from researchhub import settings

logger = logging.getLogger(__name__)


class StripeWebhookView(APIView):
    """
    View for processing Stripe webhooks.

    This view handles incoming POST requests from Stripe.

    See: https://docs.stripe.com/webhooks
    """

    permission_classes = [AllowAny]

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
            logger.warning("Failed to construct event: %s", str(e))
            return Response(
                {"message": "Invalid payload"}, status=status.HTTP_400_BAD_REQUEST
            )
        except stripe.error.SignatureVerificationError as e:
            logger.warning("Failed to validate signature: %s", str(e))
            return Response(
                {"message": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST
            )

        event_type = event["type"]
        match event_type:
            case "checkout.session.completed":
                session = event["data"]["object"]
                logger.info("Checkout session ID=%s completed", session["id"])
            case "payment_intent.succeeded":
                payment_intent = event["data"]["object"]
                logger.info("Payment intent ID=%s created", payment_intent["id"])
            case _:
                logger.info("Unhandled event type: {event_type}")

        return Response(
            {"message": "Webhook successfully processed"}, status=status.HTTP_200_OK
        )
