import logging
from typing import Dict

from analytics.interactions.amplitude_event_mapper import AmplitudeEventMapper

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
        "feed_item_clicked",
        "page_viewed",
    }

    def __init__(self):
        self.amplitude_mapper = AmplitudeEventMapper()

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

        # Must have item information in related_work (nested format)
        related_work = event_props.get("related_work", {})
        has_item_id = related_work.get("unified_document_id") or (
            related_work.get("content_type") and related_work.get("id")
        )

        if not has_item_id:
            return False

        # Only process if content_type is specified (required for document processing)
        content_type = related_work.get("content_type")
        if not content_type:
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

            # Map the event to UserInteractions (now handles duplicates internally)
            interaction = self.amplitude_mapper.map_amplitude_event_to_interaction(
                event
            )

            if interaction is None:
                logger.warning(f"Could not map event {event_type} for user {user_id}")
                return

            # Interaction is already saved by get_or_create in the mapper
            # Only log successful processing, not individual events
            logger.debug(
                f"Successfully processed interaction: {event_type} for user {user_id}"
            )

        except Exception as e:
            logger.error(f"Error processing event: {event.get('event_type')} - {e}")
