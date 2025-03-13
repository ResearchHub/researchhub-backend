import logging
from typing import Dict, List, Optional, Union

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from user.models import User
from utils.aws import create_client

logger = logging.getLogger(__name__)


class AmazonPersonalizeService:
    """
    Service for interacting with Amazon Personalize to get personalized recommendations
    for the ResearchHub feed.
    """

    def __init__(self):
        self.personalize_runtime = create_client("personalize-runtime")
        self.campaign_arn = getattr(settings, "AWS_PERSONALIZE_CAMPAIGN_ARN", None)
        self.enabled = getattr(settings, "AWS_PERSONALIZE_ENABLED", False)

    def get_recommendations(
        self, user: Optional[Union[User, AnonymousUser]], limit: int = 20
    ) -> List[Dict]:
        """
        Get personalized recommendations for a user.

        Args:
            user: The user to get recommendations for. If None or AnonymousUser,
                 will return recommendations for anonymous users.
            limit: Maximum number of recommendations to return.

        Returns:
            A list of dictionaries containing recommendation information.
            Each dictionary contains:
            - item_id: The ID of the recommended item (unified document ID)
            - score: The recommendation score
        """
        if not self.enabled or not self.campaign_arn:
            logger.warning(
                "Amazon Personalize is not enabled or campaign ARN is not set"
            )
            return []

        try:
            if user and not isinstance(user, AnonymousUser):
                # Get personalized recommendations for authenticated user
                response = self.personalize_runtime.get_recommendations(
                    campaignArn=self.campaign_arn,
                    userId=str(user.id),
                    numResults=limit,
                )
            else:
                # Get recommendations for anonymous users
                response = self.personalize_runtime.get_recommendations(
                    campaignArn=self.campaign_arn,
                    numResults=limit,
                )

            recommendations = []
            for item in response.get("itemList", []):
                recommendations.append(
                    {
                        "item_id": int(item["itemId"]),
                        "score": float(item.get("score", 0)),
                    }
                )

            return recommendations
        except Exception as e:
            logger.error(f"Error getting recommendations from Amazon Personalize: {e}")
            return []

    def record_event(
        self,
        user: Optional[Union[User, AnonymousUser]],
        item_id: int,
        event_type: str,
        event_value: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """
        Record an event in Amazon Personalize for training the recommendation model.

        Args:
            user: The user who performed the action. If None or AnonymousUser,
                 will record as anonymous user event.
            item_id: The ID of the item (unified document ID) the user interacted with.
            event_type: The type of event (e.g., 'click', 'view', 'like', 'dislike').
            event_value: Optional value associated with the event (e.g., rating).
            session_id: Optional session ID for tracking user sessions.

        Returns:
            True if the event was recorded successfully, False otherwise.
        """
        if not self.enabled:
            logger.warning("Amazon Personalize is not enabled")
            return False

        try:
            tracker = create_client("personalize-events")

            event = {
                "eventType": event_type,
                "itemId": str(item_id),
            }

            if event_value is not None:
                event["eventValue"] = float(event_value)

            properties = {"event": event}

            user_id = (
                str(user.id) if user and not isinstance(user, AnonymousUser) else None
            )

            tracker.put_events(
                trackingId=getattr(settings, "AWS_PERSONALIZE_TRACKING_ID", ""),
                userId=user_id,
                sessionId=session_id or "session-" + (user_id or "anonymous"),
                eventList=[properties],
            )

            return True
        except Exception as e:
            logger.error(f"Error recording event in Amazon Personalize: {e}")
            return False
