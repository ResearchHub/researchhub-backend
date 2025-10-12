"""
Mapper for Comment creation events.

Handles mapping of RhCommentModel records (GENERIC_COMMENT type) to Personalize
interactions, excluding comments with bounties attached.
"""

from typing import Dict, List

from analytics.services.personalize_constants import COMMENT_CREATED, EVENT_WEIGHTS
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.related_models.rh_comment_model import RhCommentModel


class CommentMapper(BaseEventMapper):
    """Mapper for comment creation events (GENERIC_COMMENT only)."""

    @property
    def event_type_name(self) -> str:
        return "comment"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get comments queryset with filters.

        Filters:
        - comment_type = GENERIC_COMMENT (excludes ANSWER, REVIEW, etc.)
        - bounties__isnull = True (excludes comments with bounties attached)
        """
        queryset = RhCommentModel.objects.select_related("created_by", "thread").filter(
            comment_type=GENERIC_COMMENT,
            bounties__isnull=True,  # CRITICAL: Exclude bounty comments
        )

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, comment: RhCommentModel) -> List[Dict]:
        """
        Map a comment to ONE COMMENT_CREATED interaction.

        Args:
            comment: RhCommentModel instance

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no creator
        if not comment.created_by:
            return interactions

        # Get unified_document via property
        # (accesses thread.content_object.unified_document)
        try:
            unified_doc = comment.unified_document
            if not unified_doc:
                return interactions
        except Exception:
            # Handle cases where thread or content_object doesn't exist
            return interactions

        user_id = str(comment.created_by.id)
        item_id = str(unified_doc.id)

        # Create COMMENT_CREATED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": COMMENT_CREATED,
            "EVENT_VALUE": EVENT_WEIGHTS[COMMENT_CREATED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(comment.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
