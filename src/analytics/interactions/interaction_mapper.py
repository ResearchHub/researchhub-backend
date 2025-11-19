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

    Raises:
        ValueError: If vote is missing required fields (user, unified_document)
    """
    # Validate required fields
    if not vote.created_by_id:
        raise ValueError(f"Vote {vote.id} has no created_by user")

    # Get unified_document (this is a property that can raise exceptions)
    try:
        unified_doc = vote.unified_document
    except Exception as e:
        raise ValueError(f"Vote {vote.id} has no valid unified_document: {str(e)}")

    if not unified_doc:
        raise ValueError(f"Vote {vote.id} has None unified_document")

    return UserInteractions(
        user=vote.created_by,
        external_user_id=None,
        event=UPVOTE,
        unified_document=unified_doc,
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
        external_user_id=amplitude_event.external_user_id,
        event=amplitude_event.event_type,
        unified_document=amplitude_event.unified_document,
        content_type=amplitude_event.content_type,
        object_id=amplitude_event.object_id,
        event_timestamp=amplitude_event.event_timestamp,
        is_synced_with_personalize=False,
        personalize_rec_id=amplitude_event.personalize_rec_id,
        impression=amplitude_event.impression,
    )
