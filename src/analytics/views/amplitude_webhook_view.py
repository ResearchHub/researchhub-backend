import hmac
import json
import logging
from hashlib import sha256

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.services.event_processor import EventProcessor
from utils.sentry import log_error

logger = logging.getLogger(__name__)


class AmplitudeWebhookView(APIView):
    """
    Webhook endpoint for receiving events from Amplitude.

    This endpoint:
    1. Receives all events from Amplitude
    2. Validates the webhook signature
    3. Processes and filters events relevant for ML/recommendations
    4. Assigns weights to different event types
    5. Prepares data for AWS Personalize

    Event Flow:
    Amplitude -> Webhook -> EventProcessor -> AWS Personalize
    """

    permission_classes = [AllowAny]

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Process incoming webhook from Amplitude.

        Expected payload format from Amplitude:
        {
            "api_key": "your_api_key",
            "events": [
                {
                    "event_type": "click",
                    "user_id": "12345",
                    "event_properties": {...},
                    "user_properties": {...},
                    "time": 1234567890000
                }
            ]
        }
        """
        try:
            # Validate signature if configured
            if (
                hasattr(settings, "AMPLITUDE_WEBHOOK_SECRET")
                and settings.AMPLITUDE_WEBHOOK_SECRET
            ):
                if not self._validate_signature(request):
                    logger.warning("Invalid Amplitude webhook signature")
                    return Response(
                        {"message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED
                    )

            # Parse the payload
            payload = json.loads(request.body)
            events = payload.get("events", [])

            if not events:
                return Response(
                    {"message": "No events in payload"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Process events
            processor = EventProcessor()
            processed_count = 0
            skipped_count = 0

            for event in events:
                try:
                    if processor.should_process_event(event):
                        processor.process_event(event)
                        processed_count += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    log_error(
                        e,
                        message=(
                            f"Failed to process individual event: "
                            f"{event.get('event_type')}"
                        ),
                    )
                    continue

            logger.info(
                f"Amplitude webhook processed: {processed_count} events, {skipped_count} skipped"
            )

            return Response(
                {
                    "message": "Webhook successfully processed",
                    "processed": processed_count,
                    "skipped": skipped_count,
                },
                status=status.HTTP_200_OK,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {e}")
            return Response(
                {"message": "Invalid JSON payload"}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            log_error(e, message="Failed to process Amplitude webhook")
            return Response(
                {"message": "Failed to process webhook"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _validate_signature(self, request: Request) -> bool:
        """
        Validate the webhook signature from Amplitude.

        Amplitude signs webhooks with HMAC-SHA256.
        """
        try:
            signature = request.headers.get("X-Amplitude-Signature")
            if not signature:
                return False

            secret = settings.AMPLITUDE_WEBHOOK_SECRET.encode("utf-8")
            expected_signature = hmac.new(secret, request.body, sha256).hexdigest()

            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            log_error(e, message="Error validating Amplitude webhook signature")
            return False
