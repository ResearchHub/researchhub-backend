import logging
from typing import Any, Dict

from analytics.constants.event_types import FEED_ITEM_CLICKED, PAGE_VIEWED
from analytics.interactions.amplitude_event_parser import AmplitudeEventParser
from analytics.interactions.interaction_mapper import map_from_amplitude_event
from analytics.models import UserInteractions

logger = logging.getLogger(__name__)


class EventProcessor:
    """Processes events from Amplitude."""

    AMPLITUDE_EVENTS = {
        FEED_ITEM_CLICKED,
        PAGE_VIEWED,
    }

    def __init__(self):
        self.amplitude_parser = AmplitudeEventParser()

    def should_process_event(self, event: Dict[str, Any]) -> bool:
        """Determine if an event should be processed."""
        event_type = event.get("event_type", "").lower()

        if event_type not in self.AMPLITUDE_EVENTS:
            return False

        event_props = event.get("event_properties", {})
        if not event_props.get("user_id"):
            return False

        related_work = event_props.get("related_work", {})
        if not related_work:
            return False

        content_type = related_work.get("content_type")
        object_id = related_work.get("id")
        unified_document_id = related_work.get("unified_document_id")
        if not content_type or not object_id or not unified_document_id:
            return False

        return True

    def process_event(self, event: Dict[str, Any]) -> None:
        """Process a single event."""
        try:
            event_type = event.get("event_type", "unknown").lower()
            event_props = event.get("event_properties", {})
            user_id = event_props.get("user_id")

            amplitude_event = self.amplitude_parser.parse_amplitude_event(event)

            if amplitude_event is None:
                logger.warning(f"Could not parse event {event_type} for user {user_id}")
                return

            interaction = map_from_amplitude_event(amplitude_event)

            try:
                interaction, created = UserInteractions.objects.get_or_create(
                    user=interaction.user,
                    event=interaction.event,
                    unified_document=interaction.unified_document,
                    content_type=interaction.content_type,
                    object_id=interaction.object_id,
                    defaults={
                        "event_timestamp": interaction.event_timestamp,
                        "is_synced_with_personalize": (
                            interaction.is_synced_with_personalize
                        ),
                        "personalize_rec_id": interaction.personalize_rec_id,
                    },
                )
                logger.debug(
                    f"Successfully processed interaction: {event_type} for user "
                    f"{user_id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to save interaction: {event_type} for user "
                    f"{user_id} - {e}"
                )

        except Exception as e:
            logger.error(f"Error processing event: {event.get('event_type')} - {e}")
