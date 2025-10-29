"""
Functional mappers for converting source records to UserInteractions.
"""

from analytics.constants.event_types import UPVOTE
from analytics.interactions.amplitude_event_parser import AmplitudeEvent
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


def map_from_amplitude_event(amplitude_event: AmplitudeEvent) -> UserInteractions:
    """
    Map an AmplitudeEvent dataclass to a UserInteractions instance.

    Args:
        amplitude_event: AmplitudeEvent dataclass with pre-fetched Django model
            instances

    Returns:
        UserInteractions instance (not saved to database)
    """
    return UserInteractions(
        user=amplitude_event.user,
        event=amplitude_event.event_type,
        unified_document=amplitude_event.unified_document,
        content_type=amplitude_event.content_type,
        object_id=amplitude_event.object_id,
        event_timestamp=amplitude_event.event_timestamp,
        is_synced_with_personalize=False,
        personalize_rec_id=None,
    )
