import logging

import stripe
from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from paper.related_models.paper_model import Paper
from purchase.related_models.payment_model import Payment, PaymentProcessor
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
            logger.warning("Failed to parse event: %s", str(e))
            return Response(
                {"message": "Invalid payload"}, status=status.HTTP_400_BAD_REQUEST
            )
        except stripe.error.SignatureVerificationError as e:
            logger.warning("Failed to validate signature: %s", str(e))
            return Response(
                {"message": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            event_type = event["type"]
            match event_type:
                case "checkout.session.completed":
                    checkout_session = event["data"]["object"]
                    self.insertPayment(checkout_session)
                    logger.info(
                        "Completed checkout session ID=%s processed",
                        checkout_session["id"],
                    )
                case "payment_intent.succeeded":
                    payment_intent = event["data"]["object"]
                    logger.info("Payment intent ID=%s created", payment_intent["id"])
                case _:
                    logger.info("Unhandled event type: {event_type}")
        except ValueError as e:
            logger.error("Invalid event data: %s", str(e))
            return Response(
                {"message": "Invalid event data"}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error("Error processing event: %s", str(e))
            return Response(
                {"message": "Error processing event"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"message": "Webhook successfully processed"}, status=status.HTTP_200_OK
        )

    def insertPayment(self, checkout_session):
        """
        Insert payment record into the database.
        """
        if "paper_id" not in checkout_session["metadata"]:
            raise ValueError("Missing paper_id in Stripe metadata")
        if "user_id" not in checkout_session["metadata"]:
            raise ValueError("Missing user_id in Stripe metadata")

        user_id = checkout_session["metadata"]["user_id"]
        paper_id = checkout_session["metadata"]["paper_id"]

        Payment.objects.create(
            amount=checkout_session["amount_total"],
            currency=checkout_session["currency"].upper(),
            external_payment_id=checkout_session["payment_intent"],
            payment_processor=PaymentProcessor.STRIPE,
            object_id=paper_id,
            content_type=ContentType.objects.get_for_model(Paper),
            user_id=user_id,
        )
