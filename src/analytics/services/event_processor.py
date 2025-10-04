import logging
from datetime import datetime
from typing import Dict

from django.conf import settings

from analytics.services.personalize_service import PersonalizeService
from user.models import User
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
        # Positive signals (interest/engagement)
        "fundraise": 3.0,  # Strongest signal - financial contribution
        "donate": 3.0,  # Same as fundraise
        "upvote": 2.0,  # Explicit support
        "share": 2.0,  # User recommends to others
        "download": 1.5,  # Saving resource
        "click": 1.0,  # Basic interest
        "view": 0.5,  # Passive exposure
        "scroll_impression": 0.7,  # Confirmed view (scrolled to it)
        "initial_impression": 0.3,  # Possible view (loaded but may not have seen)
        "bookmark": 1.8,  # Save for later
        "comment": 1.5,  # Engagement
        # Negative signals
        "flag_content": -2.5,  # Strongest negative signal
        "downvote": -1.0,  # Explicit disagreement
        "hide": -0.5,  # User doesn't want to see this
        "not_interested": -0.8,  # Explicit negative feedback
    }

    # Events that should be sent to AWS Personalize
    ML_RELEVANT_EVENTS = {
        "click",
        "upvote",
        "share",
        "download",
        "fundraise",
        "donate",
        "scroll_impression",
        "initial_impression",
        "downvote",
        "flag_content",
        "bookmark",
        "comment",
        "hide",
        "not_interested",
    }

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

        # Must have a user_id
        if not event.get("user_id"):
            return False

        # Must have item information (item_id in event_properties)
        event_props = event.get("event_properties", {})
        if not event_props.get("item_id") and not event_props.get(
            "unified_document_id"
        ):
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
            user_id = event.get("user_id")
            event_props = event.get("event_properties", {})
            timestamp = event.get("time", datetime.now().timestamp() * 1000)

            # Extract item information
            item_id = event_props.get("item_id") or event_props.get(
                "unified_document_id"
            )
            item_type = event_props.get("item_type", "document")

            # Get or create user
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                logger.warning(f"User {user_id} not found for event {event_type}")
                return

            # Get weight for this event type
            weight = self.EVENT_WEIGHTS.get(event_type, 1.0)

            # Handle impression events differently
            if event_type in ["scroll_impression", "initial_impression"]:
                self._process_impression_event(
                    user=user,
                    event_type=event_type,
                    event_props=event_props,
                    timestamp=timestamp,
                )
            else:
                # Process as interaction event
                self._process_interaction_event(
                    user=user,
                    item_id=item_id,
                    item_type=item_type,
                    event_type=event_type,
                    weight=weight,
                    timestamp=timestamp,
                    event_props=event_props,
                )

        except Exception as e:
            log_error(e, message=f"Error processing event: {event.get('event_type')}")

    def _process_interaction_event(
        self,
        user: User,
        item_id: str,
        item_type: str,
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
            #     user=user,
            #     item_id=item_id,
            #     item_type=item_type,
            #     event_type=event_type,
            #     weight=weight,
            #     timestamp=datetime.fromtimestamp(timestamp / 1000),
            #     metadata=event_props,
            # )

            # Send to AWS Personalize (async)
            if not settings.DEVELOPMENT:
                self.personalize_service.send_interaction_event(
                    user_id=str(user.id),
                    item_id=item_id,
                    event_type=event_type,
                    weight=weight,
                    timestamp=timestamp,
                )

            logger.debug(
                f"Processed interaction: {event_type} for user {user.id} on item {item_id}"
            )

        except Exception as e:
            log_error(e, message=f"Failed to process interaction event: {event_type}")

    def _process_impression_event(
        self, user: User, event_type: str, event_props: Dict, timestamp: float
    ) -> None:
        """
        Process an impression event (initial_impression, scroll_impression)

        Impression events contain multiple items that were shown to the user.
        """
        try:
            # Extract list of items shown
            items_shown = event_props.get("items_shown", [])
            if not items_shown:
                logger.warning(f"No items in impression event for user {user.id}")
                return

            weight = self.EVENT_WEIGHTS.get(event_type, 0.3)

            # TODO: Store in database when implementing database storage
            # ImpressionEvent.objects.create(
            #     user=user,
            #     event_type=event_type,
            #     items_shown=items_shown,
            #     weight=weight,
            #     timestamp=datetime.fromtimestamp(timestamp / 1000),
            #     metadata=event_props,
            # )

            # Send to AWS Personalize (impressions are important for filtering)
            if not settings.DEVELOPMENT:
                self.personalize_service.send_impression_data(
                    user_id=str(user.id), items_shown=items_shown, timestamp=timestamp
                )

            logger.debug(
                f"Processed impression: {event_type} for user {user.id} with {len(items_shown)} items"
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
