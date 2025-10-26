import logging
from typing import Dict

logger = logging.getLogger(__name__)


class EventProcessor:
    """
    Processes events from Amplitude.

    Responsibilities:
    1. Determine if an event should be processed
    2. Process a single event
    3. TODO
    """

    def should_process_event(self, event: Dict) -> bool:
        """
        Determine if an event should be processed.

        Args:
            event: Event data from Amplitude

        Returns:
            bool: Whether this event is relevant
        """
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

            logger.info(f"Processing event: {event_type} for user {user_id}")

        except Exception as e:
            logger.error(f"Error processing event: {event.get('event_type')} - {e}")
