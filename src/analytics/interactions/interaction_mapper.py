"""
Functional mappers for converting source records to UserInteractions.
"""

from analytics.constants.event_types import UPVOTE
from analytics.models import UserInteractions
from discussion.models import Vote


def map_from_upvote(vote: Vote) -> UserInteractions:
    """
    Map a Vote record (upvote) to a UserInteractions instance.

    Args:
        vote: Vote record with vote_type=UPVOTE

    Returns:
        UserInteractions instance (not saved to database)
    """
    return UserInteractions(
        user=vote.created_by,
        event=UPVOTE,
        unified_document=vote.unified_document,
        content_type=vote.content_type,
        object_id=vote.object_id,
        event_timestamp=vote.created_date,
        is_synced_with_personalize=False,
        personalize_rec_id=None,
    )
