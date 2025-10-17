"""
Mapper for Item upvote events.

Handles mapping of Vote records (vote_type=UPVOTE) to Personalize interactions.
Uses the Vote model's built-in unified_document property which correctly
handles papers, posts, and comments.
"""

from typing import Dict, List

from analytics.services.personalize_constants import EVENT_WEIGHTS, ITEM_UPVOTED
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from discussion.models import Vote


class UpvoteMapper(BaseEventMapper):
    """Mapper for item upvote events."""

    @property
    def event_type_name(self) -> str:
        return "upvote"

    def _is_self_vote(self, vote: Vote) -> bool:
        """
        Check if a vote is a self-vote (user voting on their own content).

        Returns True if:
        - Paper: vote.item.uploaded_by == vote.created_by
        - Post: vote.item.created_by == vote.created_by
        - Comment: vote.item.created_by == vote.created_by

        Args:
            vote: Vote instance to check

        Returns:
            True if self-vote, False otherwise
        """
        if not vote.created_by or not vote.item:
            return False

        item = vote.item
        voter = vote.created_by

        # Papers use 'uploaded_by' field
        if hasattr(item, "uploaded_by") and item.uploaded_by:
            return item.uploaded_by.id == voter.id

        # Posts and Comments use 'created_by' field
        if hasattr(item, "created_by") and item.created_by:
            return item.created_by.id == voter.id

        # If we can't determine, assume it's not a self-vote
        return False

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get upvotes queryset with filters.

        Filters:
        - vote_type = UPVOTE (excludes NEUTRAL and DOWNVOTE)
        """
        queryset = Vote.objects.select_related("created_by").filter(
            vote_type=Vote.UPVOTE
        )

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, vote: Vote) -> List[Dict]:
        """
        Map an upvote to ONE ITEM_UPVOTED interaction.

        Skips self-votes (users voting on their own content).

        Uses vote.unified_document property which handles:
        - Paper → paper.unified_document
        - ResearchhubPost → post.unified_document
        - RhCommentModel → comment.unified_document (via thread)

        Args:
            vote: Vote instance with vote_type=UPVOTE

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no creator
        if not vote.created_by:
            return interactions

        # Skip self-votes (users voting on their own content)
        if self._is_self_vote(vote):
            return interactions

        # Get unified_document via built-in property
        try:
            unified_doc = vote.unified_document
            if not unified_doc:
                return interactions
        except Exception:
            # Handle cases where item doesn't have unified_document
            return interactions

        user_id = str(vote.created_by.id)
        item_id = str(unified_doc.id)

        # Create ITEM_UPVOTED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": ITEM_UPVOTED,
            "EVENT_VALUE": EVENT_WEIGHTS[ITEM_UPVOTED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(vote.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
