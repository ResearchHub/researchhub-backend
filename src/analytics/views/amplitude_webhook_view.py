import json
import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.services.event_processor import EventProcessor
from utils.sentry import log_error, log_info

logger = logging.getLogger(__name__)


class AmplitudeWebhookView(APIView):
    """
    Webhook endpoint for receiving events from Amplitude.

    This endpoint receives events from Amplitude and processes them through
    EventProcessor.
    """

    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        self.processor = kwargs.pop("processor", EventProcessor())
        return super().dispatch(request, *args, **kwargs)

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
                        {"message": "No events in payload"},
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

            processed_count = 0
            failed_count = 0

            for event in events:
                try:
                    self.processor.process_event(event)
                    processed_count += 1
                except Exception as e:
                    failed_count += 1
                    log_error(
                        e,
                        message=(
                            f"Failed to process individual event: "
                            f"{event.get('event_type')}"
                        ),
                    )
                    continue

            logger.info(
                f"Amplitude webhook processed: {processed_count} events, "
                f"{failed_count} failed"
            )

            return Response(
                {
                    "message": "Webhook successfully processed",
                    "processed": processed_count,
                    "failed": failed_count,
                },
                status=status.HTTP_200_OK,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {e}")
            log_info("Invalid JSON payload received", error=e)
            return Response(
                {"message": "Invalid JSON payload"}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            log_error(e, message="Failed to process Amplitude webhook")
            return Response(
                {"message": "Failed to process webhook"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
