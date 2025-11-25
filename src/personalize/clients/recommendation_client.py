"""
Client for interacting with AWS Personalize service.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from django.conf import settings

from utils.aws import create_client

logger = logging.getLogger(__name__)


class RecommendationClient:
    """
    Client for interacting with AWS Personalize to get personalized recommendations.
    """

    NEW_CONTENT_FILTER_DAYS = 60

    def __init__(self):
        """Initialize the Personalize runtime client."""
        self.client = create_client("personalize-runtime")
        self.campaign_arn = settings.AWS_PERSONALIZE_CAMPAIGN_ARN
        self.trending_campaign_arn = settings.AWS_PERSONALIZE_TRENDING_CAMPAIGN_ARN
        self.filter_arn_gte_date = settings.AWS_PERSONALIZE_FILTER_ARN_GTE_DATE

    def get_recommendations(
        self,
        user_id: str,
        campaign_arn: str,
        filter_arn: Optional[str] = None,
        filter_values: Optional[Dict[str, str]] = None,
        num_results: int = 20,
    ) -> Dict[str, Any]:
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
                f"Requesting recommendations for user {user_id} "
                f"from campaign {campaign_arn}"
            )

            response = self.client.get_recommendations(**params)

            recommendation_id = response.get("recommendationId")
            item_list = response.get("itemList", [])
            item_ids = [item["itemId"] for item in item_list]

            logger.info(f"Retrieved {len(item_ids)} recommendations for user {user_id}")

            return {
                "item_ids": item_ids,
                "recommendation_id": recommendation_id,
            }

        except Exception as e:
            logger.error(
                f"Error getting recommendations from Personalize "
                f"for user {user_id}: {str(e)}"
            )
            raise

    def get_recommendations_for_user(
        self,
        user_id: str,
        filter: Optional[str] = None,
        num_results: int = 20,
    ) -> Dict[str, Any]:
        filter_arn = None
        filter_values = None

        # Apply filtering
        if filter == "new-content":
            # Filter to content from last N days
            cutoff_date = datetime.now() - timedelta(days=self.NEW_CONTENT_FILTER_DAYS)
            timestamp_cutoff = int(cutoff_date.timestamp())

            filter_arn = self.filter_arn_gte_date
            filter_values = {"DATE": str(timestamp_cutoff)}

            logger.info(
                f"Applying new-content filter (last "
                f"{self.NEW_CONTENT_FILTER_DAYS} days) with "
                f"timestamp: {timestamp_cutoff}"
            )

        result = self.get_recommendations(
            user_id=user_id,
            campaign_arn=self.campaign_arn,
            filter_arn=filter_arn,
            filter_values=filter_values,
            num_results=num_results,
        )

        item_ids = result.get("item_ids", [])
        return {
            "item_ids": [int(item_id) for item_id in item_ids] if item_ids else [],
            "recommendation_id": result.get("recommendation_id"),
        }

    def get_trending_items(
        self,
        num_results: int = 200,
    ) -> Dict[str, Any]:
        """
        Get global trending items from AWS Personalize.
        """
        try:
            params = {
                "campaignArn": self.trending_campaign_arn,
                "numResults": num_results,
            }

            response = self.client.get_recommendations(**params)

            recommendation_id = response.get("recommendationId")
            item_list = response.get("itemList", [])
            item_ids = [int(item["itemId"]) for item in item_list]

            return {
                "item_ids": item_ids,
                "recommendation_id": recommendation_id,
            }

        except Exception as e:
            logger.error(f"Error getting trending items from Personalize: {e}")
            raise
