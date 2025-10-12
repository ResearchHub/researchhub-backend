"""
Mapper for Proposal (Preregistration) events.

Handles mapping of ResearchhubPost PREREGISTRATION documents to Personalize
interactions.
"""

from typing import Dict, List

from analytics.services.personalize_constants import EVENT_WEIGHTS, PROPOSAL_CREATED
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


class ProposalMapper(BaseEventMapper):
    """Mapper for Proposal (Preregistration) creation events."""

    @property
    def event_type_name(self) -> str:
        return "proposal"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get preregistration posts queryset with optional date filters.

        Only includes ResearchhubPost with document_type=PREREGISTRATION.
        """
        queryset = ResearchhubPost.objects.select_related(
            "created_by", "unified_document"
        ).filter(document_type=PREREGISTRATION)

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, post: ResearchhubPost) -> List[Dict]:
        """
        Map a Preregistration ResearchhubPost to ONE PROPOSAL_CREATED interaction.

        Args:
            post: ResearchhubPost instance with document_type=PREREGISTRATION

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no unified document
        if not post.unified_document:
            return interactions

        # Skip if no creator
        if not post.created_by:
            return interactions

        user_id = str(post.created_by.id)
        item_id = str(post.unified_document.id)

        # Create PROPOSAL_CREATED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": PROPOSAL_CREATED,
            "EVENT_VALUE": EVENT_WEIGHTS[PROPOSAL_CREATED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(post.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
