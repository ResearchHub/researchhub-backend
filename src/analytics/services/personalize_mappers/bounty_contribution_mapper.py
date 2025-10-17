"""
Mapper for Bounty contribution events.

Handles mapping of child Bounty records (contributions to existing bounties)
to Personalize interactions.
"""

from typing import Dict, List

from analytics.services.personalize_constants import BOUNTY_CONTRIBUTED, EVENT_WEIGHTS
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from reputation.related_models.bounty import Bounty


class BountyContributionMapper(BaseEventMapper):
    """Mapper for bounty contribution events (child bounties)."""

    @property
    def event_type_name(self) -> str:
        return "bounty_contribution"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get bounty contributions (child bounties) with optional date filters.

        Only includes bounties with parent__isnull=False.
        """
        queryset = Bounty.objects.select_related(
            "created_by", "unified_document", "parent"
        ).filter(parent__isnull=False)

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, bounty: Bounty) -> List[Dict]:
        """
        Map a Bounty contribution to ONE BOUNTY_CONTRIBUTED interaction.

        Args:
            bounty: Bounty instance (child bounty)

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

        # Create BOUNTY_CONTRIBUTED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": BOUNTY_CONTRIBUTED,
            "EVENT_VALUE": EVENT_WEIGHTS[BOUNTY_CONTRIBUTED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(bounty.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
