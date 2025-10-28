import logging
from typing import Dict

from analytics.constants.event_types import FEED_ITEM_CLICKED, PAGE_VIEWED
from analytics.interactions.amplitude_event_parser import AmplitudeEventParser
from analytics.interactions.interaction_mapper import map_from_amplitude_event
from analytics.models import UserInteractions

logger = logging.getLogger(__name__)


class EventProcessor:
    """
    Processes events from Amplitude.

    Responsibilities:
    1. Determine if an event should be processed
    2. Process a single event
    3. TODO
    """

    AMPLITUDE_EVENTS = {
        FEED_ITEM_CLICKED,
        PAGE_VIEWED,
    }

    def __init__(self):
        self.amplitude_parser = AmplitudeEventParser()

    def should_process_event(self, event: Dict) -> bool:
        """
        Determine if an event should be processed.

        Args:
            event: Event data from Amplitude

        Returns:
            bool: Whether this event is relevant
        """

        event_type = event.get("event_type", "").lower()

        # Check if it's an ML-relevant event
        if event_type not in self.AMPLITUDE_EVENTS:
            return False

        # Must have a user_id in event_properties
        event_props = event.get("event_properties", {})
        if not event_props.get("user_id"):
            return False

        # Must have related_work with ALL required fields
        related_work = event_props.get("related_work", {})
        if not related_work:
            return False

        # Must have content_type, object_id, and unified_document_id (always required)
        content_type = related_work.get("content_type")
        object_id = related_work.get("id")
        unified_document_id = related_work.get("unified_document_id")
        if not content_type or not object_id or not unified_document_id:
            return False

        return True

    def process_event(self, event: Dict) -> None:
        """
        Process a single event.

        Args:
            event: Event data from Amplitude
        """
        try:
            event_type = event.get("event_type", "unknown").lower()
            event_props = event.get("event_properties", {})
            user_id = event_props.get("user_id")

            # Parse the event to get AmplitudeEvent dataclass
            amplitude_event = self.amplitude_parser.parse_amplitude_event(event)

            if amplitude_event is None:
                logger.warning(f"Could not parse event {event_type} for user {user_id}")
                return

            # Convert to UserInteractions instance
            interaction = map_from_amplitude_event(amplitude_event)

            # Save to database with duplicate handling
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
                # Only log successful processing, not individual events
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
