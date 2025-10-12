"""
Mapper for Peer Review creation events.

Handles mapping of Review records to Personalize interactions.
"""

from typing import Dict, List

from analytics.services.personalize_constants import EVENT_WEIGHTS, PEER_REVIEW_CREATED
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from review.models.review_model import Review


class PeerReviewMapper(BaseEventMapper):
    """Mapper for peer review creation events."""

    @property
    def event_type_name(self) -> str:
        return "peer_review"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get peer reviews queryset with optional date filters.

        Includes all peer reviews.
        """
        queryset = Review.objects.select_related("created_by", "unified_document").all()

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, review: Review) -> List[Dict]:
        """
        Map a Review to ONE PEER_REVIEW_CREATED interaction.

        Args:
            review: Review instance

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no unified document
        if not review.unified_document:
            return interactions

        # Skip if no creator
        if not review.created_by:
            return interactions

        user_id = str(review.created_by.id)
        item_id = str(review.unified_document.id)

        # Create PEER_REVIEW_CREATED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": PEER_REVIEW_CREATED,
            "EVENT_VALUE": EVENT_WEIGHTS[PEER_REVIEW_CREATED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(review.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
