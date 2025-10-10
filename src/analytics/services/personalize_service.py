import logging
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from django.conf import settings

from utils.sentry import log_error

logger = logging.getLogger(__name__)


class PersonalizeService:
    """
    Service for interacting with AWS Personalize.

    AWS Personalize is used to generate personalized recommendations
    based on user interactions and impressions.

    Documentation: https://docs.aws.amazon.com/personalize/
    """

    def __init__(self):
        """Initialize AWS Personalize client."""
        self.client = None
        self.events_client = None
        self.tracking_id = getattr(settings, "AWS_PERSONALIZE_TRACKING_ID", None)

        # Only initialize if we have AWS credentials
        if hasattr(settings, "AWS_REGION_NAME") and not settings.DEVELOPMENT:
            try:
                self.client = boto3.client(
                    "personalize", region_name=settings.AWS_REGION_NAME
                )
                self.events_client = boto3.client(
                    "personalize-events", region_name=settings.AWS_REGION_NAME
                )
            except Exception as e:
                log_error(e, message="Failed to initialize AWS Personalize client")

    def send_interaction_event(
        self,
        user_id: str,
        item_id: str,
        event_type: str,
        weight: float,
        timestamp: float,
        properties: Optional[Dict] = None,
    ) -> bool:
        """
        Send an interaction event to AWS Personalize.

        Args:
            user_id: User ID
            item_id: Item ID (unified_document_id)
            event_type: Type of event (click, upvote, etc.)
            weight: Event weight
            timestamp: Event timestamp (milliseconds since epoch)
            properties: Additional event properties

        Returns:
            bool: Success status
        """
        if not self.events_client or not self.tracking_id:
            logger.debug("AWS Personalize not configured, skipping event")
            return False

        try:
            event_properties = properties or {}
            event_properties["weight"] = weight

            self.events_client.put_events(
                trackingId=self.tracking_id,
                userId=user_id,
                sessionId=event_properties.get(
                    "session_id", f"{user_id}_{int(timestamp)}"
                ),
                eventList=[
                    {
                        "eventId": f"{user_id}_{item_id}_{event_type}_{int(timestamp)}",
                        "eventType": event_type,
                        "sentAt": datetime.now(),
                        "itemId": item_id,
                        "properties": str(event_properties),
                    }
                ],
            )

            logger.debug(
                f"Sent interaction event to Personalize: {event_type} for user {user_id}"
            )
            return True

        except Exception as e:
            log_error(
                e,
                message="Failed to send interaction event to AWS Personalize",
                json_data={
                    "user_id": user_id,
                    "item_id": item_id,
                    "event_type": event_type,
                },
            )
            return False

    def send_impression_data(
        self, user_id: str, items_shown: List[str], timestamp: float
    ) -> bool:
        """
        Send impression data to AWS Personalize.

        Impressions are VERY important for ML - they help the system understand
        what the user saw but didn't interact with (negative signals).

        Args:
            user_id: User ID
            items_shown: List of item IDs that were shown
            timestamp: Timestamp (milliseconds since epoch)

        Returns:
            bool: Success status
        """
        if not self.events_client or not self.tracking_id:
            logger.debug("AWS Personalize not configured, skipping impression")
            return False

        try:
            # AWS Personalize expects impressions as a comma-separated
            # string
            impression_string = "|".join(map(str, items_shown))

            self.events_client.put_events(
                trackingId=self.tracking_id,
                userId=user_id,
                sessionId=f"{user_id}_{int(timestamp)}",
                eventList=[
                    {
                        "eventId": f"{user_id}_impression_{int(timestamp)}",
                        "eventType": "impression",
                        "sentAt": datetime.now(),
                        "impression": impression_string,
                        "properties": str({"timestamp": timestamp}),
                    }
                ],
            )

            logger.debug(
                f"Sent impression data to Personalize for user {user_id}: {len(items_shown)} items"
            )
            return True

        except Exception as e:
            log_error(
                e,
                message="Failed to send impression data to AWS Personalize",
                json_data={"user_id": user_id, "items_count": len(items_shown)},
            )
            return False

    def get_recommendations(
        self, user_id: str, num_results: int = 20, filter_arn: Optional[str] = None
    ) -> List[Dict]:
        """
        Get personalized recommendations for a user.

        Args:
            user_id: User ID
            num_results: Number of recommendations to return
            filter_arn: Optional filter ARN to apply

        Returns:
            List of recommended items with scores
        """
        if not self.client:
            logger.debug("AWS Personalize not configured")
            return []

        try:
            campaign_arn = getattr(settings, "AWS_PERSONALIZE_CAMPAIGN_ARN", None)
            if not campaign_arn:
                logger.warning("AWS Personalize campaign ARN not configured")
                return []

            request_params = {
                "campaignArn": campaign_arn,
                "userId": user_id,
                "numResults": num_results,
            }

            if filter_arn:
                request_params["filterArn"] = filter_arn

            response = self.client.get_recommendations(**request_params)

            recommendations = []
            for item in response.get("itemList", []):
                recommendations.append(
                    {"item_id": item.get("itemId"), "score": item.get("score", 0.0)}
                )

            logger.info(
                f"Retrieved {len(recommendations)} recommendations for user {user_id}"
            )
            return recommendations

        except Exception as e:
            log_error(
                e,
                message="Failed to get recommendations from AWS Personalize",
                json_data={"user_id": user_id},
            )
            return []

    def get_similar_items(self, item_id: str, num_results: int = 10) -> List[Dict]:
        """
        Get similar items based on an item.

        Args:
            item_id: Item ID to find similar items for
            num_results: Number of similar items to return

        Returns:
            List of similar items with scores
        """
        if not self.client:
            logger.debug("AWS Personalize not configured")
            return []

        try:
            campaign_arn = getattr(settings, "AWS_PERSONALIZE_SIMS_CAMPAIGN_ARN", None)
            if not campaign_arn:
                logger.warning("AWS Personalize SIMS campaign ARN not configured")
                return []

            response = self.client.get_recommendations(
                campaignArn=campaign_arn, itemId=item_id, numResults=num_results
            )

            similar_items = []
            for item in response.get("itemList", []):
                similar_items.append(
                    {"item_id": item.get("itemId"), "score": item.get("score", 0.0)}
                )

            logger.info(
                f"Retrieved {len(similar_items)} similar items for item {item_id}"
            )
            return similar_items

        except Exception as e:
            log_error(
                e,
                message="Failed to get similar items from AWS Personalize",
                json_data={"item_id": item_id},
            )
            return []
