import json
import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.tasks import process_amplitude_event
from utils.sentry import log_error, log_info

logger = logging.getLogger(__name__)


class AmplitudeWebhookView(APIView):
    """
    Webhook endpoint for receiving events from Amplitude.

    This endpoint receives events from Amplitude and processes them
    asynchronously via Celery.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Process incoming webhook from Amplitude.

        Expected payload format from Amplitude:
        {
            "event_type": "click",
            "user_id": "12345",
            "event_properties": {...},
            "user_properties": {...},
            "time": 1234567890000
        }
        """
        try:
            # Parse the payload
            payload = json.loads(request.body)

            if "events" in payload:
                events = payload.get("events", [])
                if not events:
                    log_info("Empty events array received in webhook payload")
                    return Response(
                        {"message": "Empty events array"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                if not payload.get("event_type"):
                    log_info("Invalid event format - missing event_type")
                    return Response(
                        {"message": "Invalid event format - missing event_type"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                events = [payload]

            # Queue all events for async processing
            for event in events:
                process_amplitude_event.delay(event)

            logger.info(f"Amplitude webhook queued {len(events)} events for processing")

            return Response(
                {"queued": len(events)},
                status=status.HTTP_200_OK,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {e}")
            log_info("Invalid JSON payload received", error=e)
            return Response(
                {"message": f"Invalid JSON payload: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            log_error(e, message="Failed to process Amplitude webhook")
            return Response(
                {"message": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
