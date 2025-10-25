"""
Mapper for bounty solution events.

Handles mapping of BountySolution records to Personalize interactions.
"""

from typing import Dict, List

from analytics.services.personalize_constants import (
    BOUNTY_SOLUTION_AWARDED,
    BOUNTY_SOLUTION_SUBMITTED,
    EVENT_WEIGHTS,
)
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import (
    datetime_to_epoch_seconds,
    get_unified_document_id,
)
from reputation.related_models.bounty import BountySolution


class BountySolutionMapper(BaseEventMapper):
    """Mapper for bounty solution submitted and awarded events."""

    @property
    def event_type_name(self) -> str:
        return "bounty_solution"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get bounty solutions queryset with optional date filters.

        Only includes SUBMITTED and AWARDED solutions.
        """
        queryset = BountySolution.objects.select_related(
            "created_by", "content_type", "bounty"
        ).filter(
            status__in=[BountySolution.Status.SUBMITTED, BountySolution.Status.AWARDED]
        )

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, bounty_solution: BountySolution) -> List[Dict]:
        """
        Map a BountySolution to ONE interaction record based on status.

        Creates:
        - SUBMITTED interaction (if status is SUBMITTED, using created_date)
        - AWARDED interaction (if status is AWARDED, using updated_date)
        """
        interactions = []

        # Extract unified document ID
        unified_doc_id = get_unified_document_id(
            bounty_solution.content_type, bounty_solution.object_id
        )

        if unified_doc_id is None:
            return interactions

        user_id = str(bounty_solution.created_by.id)
        item_id = str(unified_doc_id)

        # Create interaction based on current status
        if bounty_solution.status == BountySolution.Status.SUBMITTED:
            # SUBMITTED event
            interaction = {
                "USER_ID": user_id,
                "ITEM_ID": item_id,
                "EVENT_TYPE": BOUNTY_SOLUTION_SUBMITTED,
                "EVENT_VALUE": EVENT_WEIGHTS[BOUNTY_SOLUTION_SUBMITTED],
                "DEVICE": None,
                "TIMESTAMP": datetime_to_epoch_seconds(bounty_solution.created_date),
                "IMPRESSION": None,
                "RECOMMENDATION_ID": None,
            }
            interactions.append(interaction)

        elif bounty_solution.status == BountySolution.Status.AWARDED:
            # AWARDED event
            interaction = {
                "USER_ID": user_id,
                "ITEM_ID": item_id,
                "EVENT_TYPE": BOUNTY_SOLUTION_AWARDED,
                "EVENT_VALUE": EVENT_WEIGHTS[BOUNTY_SOLUTION_AWARDED],
                "DEVICE": None,
                "TIMESTAMP": datetime_to_epoch_seconds(bounty_solution.updated_date),
                "IMPRESSION": None,
                "RECOMMENDATION_ID": None,
            }
            interactions.append(interaction)

        return interactions
