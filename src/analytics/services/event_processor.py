import logging
from typing import Any, Dict

from analytics.interactions.amplitude_event_parser import AmplitudeEventParser
from analytics.interactions.interaction_mapper import map_from_amplitude_event
from analytics.models import UserInteractions

logger = logging.getLogger(__name__)


class EventProcessor:
    """Processes events from Amplitude."""

    def __init__(self):
        self.amplitude_parser = AmplitudeEventParser()

    def process_event(self, event: Dict[str, Any]) -> None:
        """Process a single event."""
        event_type = event.get("event_type", "unknown").lower()
        event_props = event.get("event_properties", {})
        user_id = event_props.get("user_id") or event.get("user_id")
        external_user_id = event.get("amplitude_id") or event_props.get("amplitude_id")

        # Check parsing first - raise exception if it fails
        amplitude_event = self.amplitude_parser.parse_amplitude_event(event)
        if amplitude_event is None:
            user_identifier = (
                user_id
                if user_id
                else (f"external_user_id:{external_user_id}" if external_user_id else "unknown")
            )
            error_msg = f"Could not parse event {event_type} for user {user_identifier}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        interaction = map_from_amplitude_event(amplitude_event)

        try:
            lookup_kwargs = {
                "event": interaction.event,
                "unified_document": interaction.unified_document,
                "content_type": interaction.content_type,
                "object_id": interaction.object_id,
            }

            if interaction.event in ["FEED_ITEM_CLICK", "PAGE_VIEW"]:
                lookup_kwargs["event_timestamp__date"] = (
                    interaction.event_timestamp.date()
                )

            if interaction.external_user_id:
                lookup_kwargs["external_user_id"] = interaction.external_user_id
            else:
                lookup_kwargs["user"] = interaction.user
                lookup_kwargs["external_user_id__isnull"] = True

            interaction, created = UserInteractions.objects.get_or_create(
                **lookup_kwargs,
                defaults={
                    "user": interaction.user,
                    "external_user_id": interaction.external_user_id,
                    "event_timestamp": interaction.event_timestamp,
                    "is_synced_with_personalize": (
                        interaction.is_synced_with_personalize
                    ),
                    "personalize_rec_id": interaction.personalize_rec_id,
                    "impression": interaction.impression,
                },
            )
            user_identifier = user_id if user_id else f"external_user_id:{external_user_id}"
            logger.debug(
                f"Successfully processed interaction: {event_type} for user "
                f"{user_identifier}"
            )
        except Exception as e:
            user_identifier = user_id if user_id else f"external_user_id:{external_user_id}"
            logger.error(
                f"Failed to save interaction: {event_type} for user "
                f"{user_identifier} - {e}"
            )
            # Re-raise so webhook view can count it as failed
            raise
