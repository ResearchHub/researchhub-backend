"""
Mapper for Proposal funding events.

Handles mapping of Purchase records with type FUNDRAISE_CONTRIBUTION
to Personalize interactions.
"""

from typing import Dict, List

from analytics.services.personalize_constants import EVENT_WEIGHTS, PROPOSAL_FUNDED
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from purchase.related_models.purchase_model import Purchase


class ProposalFundingMapper(BaseEventMapper):
    """Mapper for proposal funding events (fundraise contributions)."""

    @property
    def event_type_name(self) -> str:
        return "proposal_funding"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get fundraise contribution purchases with optional date filters.

        Filters for purchase_type='FUNDRAISE_CONTRIBUTION'.
        """
        queryset = Purchase.objects.select_related("user", "content_type").filter(
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION
        )

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, purchase: Purchase) -> List[Dict]:
        """
        Map a fundraise contribution to ONE PROPOSAL_FUNDED interaction.

        Args:
            purchase: Purchase instance with type FUNDRAISE_CONTRIBUTION

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no user
        if not purchase.user:
            return interactions

        # Get the fundraise via GenericForeignKey
        try:
            fundraise = purchase.item
            if not fundraise:
                return interactions
        except Exception:
            # Handle cases where the item doesn't exist
            return interactions

        # Skip if fundraise has no unified document
        if not hasattr(fundraise, "unified_document") or not fundraise.unified_document:
            return interactions

        user_id = str(purchase.user.id)
        item_id = str(fundraise.unified_document.id)

        # Create PROPOSAL_FUNDED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": PROPOSAL_FUNDED,
            "EVENT_VALUE": EVENT_WEIGHTS[PROPOSAL_FUNDED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(purchase.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
