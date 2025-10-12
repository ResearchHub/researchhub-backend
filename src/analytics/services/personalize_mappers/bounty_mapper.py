"""
Mapper for Bounty creation events.

Handles mapping of Bounty records to Personalize interactions.
"""

from typing import Dict, List

from analytics.services.personalize_constants import BOUNTY_CREATED, EVENT_WEIGHTS
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from reputation.related_models.bounty import Bounty


class BountyMapper(BaseEventMapper):
    """Mapper for bounty creation events."""

    @property
    def event_type_name(self) -> str:
        return "bounty"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get bounties queryset with optional date filters.

        Includes all bounties.
        """
        queryset = Bounty.objects.select_related("created_by", "unified_document").all()

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, bounty: Bounty) -> List[Dict]:
        """
        Map a Bounty to ONE BOUNTY_CREATED interaction.

        Args:
            bounty: Bounty instance

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no unified document
        if not bounty.unified_document:
            return interactions

        # Skip if no creator
        if not bounty.created_by:
            return interactions

        user_id = str(bounty.created_by.id)
        item_id = str(bounty.unified_document.id)

        # Create BOUNTY_CREATED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": BOUNTY_CREATED,
            "EVENT_VALUE": EVENT_WEIGHTS[BOUNTY_CREATED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(bounty.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
