"""
Mapper for Preprint submission events.

Handles mapping of user-submitted Paper records (preprints) to Personalize
interactions. Only tracks papers uploaded by users, not those imported from
external sources like arXiv, bioRxiv, or OpenAlex.
"""

from typing import Dict, List

from analytics.services.personalize_constants import EVENT_WEIGHTS, PREPRINT_SUBMITTED
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from paper.models import Paper


class PreprintMapper(BaseEventMapper):
    """Mapper for preprint submission events."""

    @property
    def event_type_name(self) -> str:
        return "preprint"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get user-submitted preprints queryset with filters.

        Filters:
        - retrieved_from_external_source=False (user-submitted only)
        - work_type='preprint' (preprints specifically)
        - uploaded_by__isnull=False (must have uploader)
        """
        queryset = Paper.objects.select_related(
            "uploaded_by", "unified_document"
        ).filter(
            retrieved_from_external_source=False,
            work_type="preprint",
            uploaded_by__isnull=False,
        )

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, paper: Paper) -> List[Dict]:
        """
        Map a preprint submission to ONE PREPRINT_SUBMITTED interaction.

        Args:
            paper: Paper instance (user-submitted preprint)

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no uploader or no unified document
        if not paper.uploaded_by or not paper.unified_document:
            return interactions

        user_id = str(paper.uploaded_by.id)
        item_id = str(paper.unified_document.id)

        # Create PREPRINT_SUBMITTED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": PREPRINT_SUBMITTED,
            "EVENT_VALUE": EVENT_WEIGHTS[PREPRINT_SUBMITTED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(paper.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
