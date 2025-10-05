import logging
from datetime import datetime
from typing import Dict

from django.conf import settings

from analytics.services.personalize_service import PersonalizeService
from utils.sentry import log_error

logger = logging.getLogger(__name__)


class EventProcessor:
    """
    Processes events from Amplitude and prepares them for ML/recommendations.

    Responsibilities:
    1. Filter events relevant for recommendations
    2. Assign weights to different event types
    3. Send data to AWS Personalize
    4. TODO: Store processed events in database (future enhancement)
    """

    # Event weights based on importance for understanding user interests
    EVENT_WEIGHTS = {
        "vote_action": 2.0,  # User voting indicates strong preference
        "feed_item_clicked": 1.5,  # User actively engaged with content
        "proposal_funded": 3.0,  # Strongest signal - financial contribution
        "comment_created": 2.5,  # High engagement - user took time to write
        "peer_review_created": 2.8,  # Very high engagement - expert contribution
    }

    # Events that should be sent to AWS Personalize
    ML_RELEVANT_EVENTS = {
        "vote_action",
        "feed_item_clicked",
        "proposal_funded",
        "comment_created",
        "peer_review_created",
    }

    # Impression events (currently empty, can be added later)
    IMPRESSION_EVENTS = set()

    def __init__(self):
        self.personalize_service = PersonalizeService()

    def should_process_event(self, event: Dict) -> bool:
        """
        Determine if an event should be processed for ML.

        Args:
            event: Event data from Amplitude

        Returns:
            bool: Whether this event is relevant for ML/recommendations
        """
        event_type = event.get("event_type", "").lower()

        # Check if it's an ML-relevant event
        if event_type not in self.ML_RELEVANT_EVENTS:
            return False

        # Must have a user_id in event_properties
        event_props = event.get("event_properties", {})
        if not event_props.get("user_id"):
            return False

        # Must have item information in related_work (flattened format)
        has_item_id = event_props.get("related_work.unified_document_id") or (
            event_props.get("related_work.content_type")
            and event_props.get("related_work.id")
        )

        if not has_item_id:
            return False

        # Only process if content_type is specified (required for document processing)
        content_type = event_props.get("related_work.content_type")
        if not content_type:
            return False

        return True

    def process_event(self, event: Dict) -> None:
        """
        Process a single event and prepare it for ML.

        Args:
            event: Event data from Amplitude
        """
        try:
            event_type = event.get("event_type", "").lower()
            event_props = event.get("event_properties", {})
            user_id = event_props.get("user_id")

            # Handle flattened related_work format
            unified_doc_id = event_props.get("related_work.unified_document_id")
            content_type = event_props.get("related_work.content_type")
            related_id = event_props.get("related_work.id")

            if unified_doc_id:
                item_id = unified_doc_id
            elif content_type and related_id:
                item_id = f"{content_type}_{related_id}"
            else:
                item_id = None

            # Use content_type from related_work, default to 'unknown' if not specified
            content_type = content_type or "unknown"
            timestamp = event.get("time", datetime.now().timestamp() * 1000)

            # PERFORMANCE CONCERN: User loading commented out to avoid DB query per event
            # This could be costly with thousands of events. AWS Personalize will handle
            # invalid user IDs gracefully, so we skip user validation for performance.
            # Uncomment below if user validation is needed for debugging:
            # try:
            #     user = User.objects.get(id=user_id)
            # except User.DoesNotExist:
            #     logger.warning(f"User {user_id} not found for event {event_type}")
            #     return

            # Get weight for this event type
            weight = self.EVENT_WEIGHTS.get(event_type, 1.0)

            # Handle impression events differently
            if event_type in self.IMPRESSION_EVENTS:
                self._process_impression_event(
                    user_id=user_id,
                    event_type=event_type,
                    event_props=event_props,
                    timestamp=timestamp,
                )
            else:
                # Process as interaction event
                self._process_interaction_event(
                    user_id=user_id,
                    item_id=item_id,
                    content_type=content_type,
                    event_type=event_type,
                    weight=weight,
                    timestamp=timestamp,
                    event_props=event_props,
                )

        except Exception as e:
            log_error(e, message=f"Error processing event: {event.get('event_type')}")

    def _process_interaction_event(
        self,
        user_id: str,
        item_id: str,
        content_type: str,
        event_type: str,
        weight: float,
        timestamp: float,
        event_props: Dict,
    ) -> None:
        """
        Process an interaction event (click, upvote, etc.)
        """
        try:
            # TODO: Store in database when implementing database storage
            # UserInteraction.objects.create(
            #     user_id=user_id,
            #     item_id=item_id,
            #     content_type=content_type,
            #     event_type=event_type,
            #     weight=weight,
            #     timestamp=datetime.fromtimestamp(timestamp / 1000),
            #     metadata=event_props,
            # )

            # Send to AWS Personalize (async)
            if not settings.DEVELOPMENT:
                self.personalize_service.send_interaction_event(
                    user_id=user_id,
                    item_id=item_id,
                    event_type=event_type,
                    weight=weight,
                    timestamp=timestamp,
                )

            logger.debug(
                f"Processed interaction: {event_type} for user {user_id} on item {item_id} (type: {content_type})"
            )

        except Exception as e:
            log_error(e, message=f"Failed to process interaction event: {event_type}")

    def _process_impression_event(
        self,
        user_id: str,
        event_type: str,
        event_props: Dict,
        timestamp: float,
    ) -> None:
        """
        Process an impression event (initial_impression, scroll_impression)

        Impression events contain multiple items that were shown to the user.
        """
        try:
            # Extract list of items shown
            items_shown = event_props.get("items_shown", [])
            if not items_shown:
                logger.warning(f"No items in impression event for user {user_id}")
                return

            weight = self.EVENT_WEIGHTS.get(event_type, 0.3)

            # TODO: Store in database when implementing database storage
            # ImpressionEvent.objects.create(
            #     user_id=user_id,
            #     event_type=event_type,
            #     items_shown=items_shown,
            #     weight=weight,
            #     timestamp=datetime.fromtimestamp(timestamp / 1000),
            #     metadata=event_props,
            # )

            # Send to AWS Personalize (impressions are important for filtering)
            if not settings.DEVELOPMENT:
                self.personalize_service.send_impression_data(
                    user_id=user_id,
                    items_shown=items_shown,
                    timestamp=timestamp,
                )

            logger.debug(
                f"Processed impression: {event_type} for user {user_id} with {len(items_shown)} items"
            )

        except Exception as e:
            log_error(e, message=f"Failed to process impression event: {event_type}")

    def get_event_weight(self, event_type: str) -> float:
        """
        Get the weight for a given event type.

        Args:
            event_type: Type of event

        Returns:
            float: Weight value
        """
        return self.EVENT_WEIGHTS.get(event_type.lower(), 1.0)
