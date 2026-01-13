import logging
from typing import Any, Dict

from django.db import transaction

from analytics.constants.event_types import BULK_FEED_IMPRESSION
from analytics.interactions.amplitude_event_parser import AmplitudeEventParser
from analytics.interactions.interaction_mapper import map_from_amplitude_event
from analytics.models import UserInteractions

logger = logging.getLogger(__name__)


class EventProcessor:
    """Processes events from Amplitude."""

    # Event types that are processed as bulk events (one input -> multiple records)
    BULK_EVENT_TYPES = {BULK_FEED_IMPRESSION}

    def __init__(self):
        self.amplitude_parser = AmplitudeEventParser()

    def process_event(self, event: Dict[str, Any]) -> None:
        """
        Process an event, routing to appropriate handler based on event type.

        Args:
            event: The Amplitude event data

        Raises:
            ValueError: If event cannot be parsed or is missing required data
        """
        event_type = event.get("event_type", "unknown").lower()

        if event_type in self.BULK_EVENT_TYPES:
            self._process_bulk_event(event)
        else:
            self._process_single_event(event)

    def _process_single_event(self, event: Dict[str, Any]) -> None:
        """Process a single event that creates one interaction record."""
        event_type = event.get("event_type", "unknown").lower()
        event_props = event.get("event_properties", {})
        user_id = event_props.get("user_id") or event.get("user_id")
        external_user_id = event.get("amplitude_id") or event_props.get("amplitude_id")

        # Check parsing first - raise exception if it fails
        amplitude_event = self.amplitude_parser.parse_amplitude_event(event)
        if amplitude_event is None:
            user_identifier = self._get_user_identifier(user_id, external_user_id)
            error_msg = f"Could not parse event {event_type} for user {user_identifier}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        interaction = map_from_amplitude_event(amplitude_event)

        try:
            lookup_kwargs = {
                "event": interaction.event,
                "unified_document_id": interaction.unified_document_id,
                "content_type": interaction.content_type,
                "object_id": interaction.object_id,
            }

            if interaction.event in [
                "FEED_ITEM_CLICK",
                "PAGE_VIEW",
                "DOCUMENT_TAB_CLICKED",
            ]:
                lookup_kwargs["event_timestamp__date"] = (
                    interaction.event_timestamp.date()
                )

            if interaction.external_user_id:
                lookup_kwargs["external_user_id"] = interaction.external_user_id
            else:
                lookup_kwargs["user_id"] = interaction.user_id
                lookup_kwargs["external_user_id__isnull"] = True

            interaction, created = UserInteractions.objects.get_or_create(
                **lookup_kwargs,
                defaults={
                    "user_id": interaction.user_id,
                    "external_user_id": interaction.external_user_id,
                    "event_timestamp": interaction.event_timestamp,
                    "is_synced_with_personalize": False,
                    "personalize_rec_id": interaction.personalize_rec_id,
                    "impression": interaction.impression,
                },
            )

            user_identifier = self._get_user_identifier(user_id, external_user_id)
            logger.debug(
                f"Successfully processed interaction: {event_type} "
                f"for user {user_identifier}"
            )

        except Exception as e:
            user_identifier = self._get_user_identifier(user_id, external_user_id)
            logger.error(
                f"Failed to save interaction: {event_type} "
                f"for user {user_identifier} - {e}"
            )
            raise

    def _process_bulk_event(self, event: Dict[str, Any]) -> None:
        """Process a bulk event that creates multiple interaction records."""
        event_props = event.get("event_properties", {})
        user_id = event_props.get("user_id") or event.get("user_id")
        external_user_id = event.get("amplitude_id") or event_props.get("amplitude_id")

        if not user_id and not external_user_id:
            error_msg = "No user_id or external_user_id for bulk event"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Parse the bulk event into individual AmplitudeEvent objects
        amplitude_events = self.amplitude_parser.parse_bulk_impression_event(event)

        user_identifier = self._get_user_identifier(user_id, external_user_id)

        if not amplitude_events:
            logger.warning(f"No valid impressions parsed for user {user_identifier}")
            return

        created_count = 0
        failed_count = 0

        for amplitude_event in amplitude_events:
            try:
                interaction = map_from_amplitude_event(amplitude_event)

                lookup_kwargs = {
                    "event": interaction.event,
                    "unified_document_id": interaction.unified_document_id,
                    "content_type": interaction.content_type,
                    "object_id": interaction.object_id,
                    "event_timestamp__date": interaction.event_timestamp.date(),
                }

                if interaction.external_user_id:
                    lookup_kwargs["external_user_id"] = interaction.external_user_id
                else:
                    lookup_kwargs["user_id"] = interaction.user_id
                    lookup_kwargs["external_user_id__isnull"] = True

                # Use savepoint so FK violations don't break the whole batch
                with transaction.atomic():
                    _, created = UserInteractions.objects.get_or_create(
                        **lookup_kwargs,
                        defaults={
                            "user_id": interaction.user_id,
                            "external_user_id": interaction.external_user_id,
                            "event_timestamp": interaction.event_timestamp,
                            "is_synced_with_personalize": False,
                            "personalize_rec_id": interaction.personalize_rec_id,
                            "impression": interaction.impression,
                        },
                    )

                if created:
                    created_count += 1

            except Exception as e:
                logger.error(
                    f"Failed to save impression for user {user_identifier}: {e}"
                )
                failed_count += 1
                continue

        duplicate_count = len(amplitude_events) - created_count - failed_count
        logger.debug(
            f"Processed bulk event for user {user_identifier}: "
            f"{created_count} created, {failed_count} failed, "
            f"{duplicate_count} duplicates"
        )

    @staticmethod
    def _get_user_identifier(user_id: Any, external_user_id: Any) -> str:
        """Get a user identifier string for logging."""
        if user_id:
            return str(user_id)
        elif external_user_id:
            return f"external_user_id:{external_user_id}"
        return "unknown"
