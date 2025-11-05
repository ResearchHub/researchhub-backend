"""
Client for interacting with AWS Personalize service.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from utils.aws import create_client

logger = logging.getLogger(__name__)


class PersonalizeClient:
    """
    Client for interacting with AWS Personalize to get personalized recommendations.
    """

    # AWS Personalize Configuration
    CAMPAIGN_ARN = "arn:aws:personalize:us-west-2:975049929542:campaign/for-your"
    FILTER_ARN_GTE_DATE = (
        "arn:aws:personalize:us-west-2:975049929542:filter/filter-gte-date"
    )
    NEW_CONTENT_FILTER_DAYS = 60

    def __init__(self):
        """Initialize the Personalize runtime client."""
        self.client = create_client("personalize-runtime")

    def get_recommendations(
        self,
        user_id: str,
        campaign_arn: str,
        filter_arn: Optional[str] = None,
        filter_values: Optional[Dict[str, str]] = None,
        num_results: int = 20,
    ) -> List[str]:
        """
        Get personalized recommendations from AWS Personalize.
        """
        try:
            params = {
                "campaignArn": campaign_arn,
                "userId": str(user_id),
                "numResults": num_results,
            }

            # Add filter parameters if provided
            if filter_arn and filter_values:
                params["filterArn"] = filter_arn
                params["filterValues"] = filter_values

            logger.info(
                f"Requesting recommendations for user {user_id} from campaign {campaign_arn}"
            )

            response = self.client.get_recommendations(**params)

            # Extract item IDs from response
            item_list = response.get("itemList", [])
            item_ids = [item["itemId"] for item in item_list]

            logger.info(f"Retrieved {len(item_ids)} recommendations for user {user_id}")

            return item_ids

        except Exception as e:
            logger.error(
                f"Error getting recommendations from Personalize for user {user_id}: {str(e)}"
            )
            raise

    def get_recommendations_for_user(
        self,
        user_id: str,
        filter: Optional[str] = None,
        num_results: int = 20,
    ) -> List[str]:
        """
        Get personalized recommendations for a user with optional filtering.
        """
        filter_arn = None
        filter_values = None

        # Apply filter-specific filtering
        if filter == "new-content":
            # Filter to content from last N days
            cutoff_date = datetime.now() - timedelta(days=self.NEW_CONTENT_FILTER_DAYS)
            timestamp_cutoff = int(cutoff_date.timestamp())

            filter_arn = self.FILTER_ARN_GTE_DATE
            filter_values = {"DATE": str(timestamp_cutoff)}

            logger.info(
                f"Applying new-content filter (last "
                f"{self.NEW_CONTENT_FILTER_DAYS} days) with "
                f"timestamp: {timestamp_cutoff}"
            )

        return self.get_recommendations(
            user_id=user_id,
            campaign_arn=self.CAMPAIGN_ARN,
            filter_arn=filter_arn,
            filter_values=filter_values,
            num_results=num_results,
        )
