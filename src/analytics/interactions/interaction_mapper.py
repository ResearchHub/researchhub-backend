"""
Functional mappers for converting source records to UserInteractions.
"""

from analytics.interactions.amplitude_event_parser import AmplitudeEvent
from analytics.models import UserInteractions


def map_from_amplitude_event(amplitude_event: AmplitudeEvent) -> UserInteractions:
    """
    Map an AmplitudeEvent dataclass to a UserInteractions instance.

    Args:
        amplitude_event: AmplitudeEvent dataclass with IDs for user and document

    Returns:
        UserInteractions instance (not saved to database).
    """
    return UserInteractions(
        user_id=amplitude_event.user_id,
        external_user_id=amplitude_event.external_user_id,
        event=amplitude_event.event_type,
        unified_document_id=amplitude_event.unified_document_id,
        content_type=amplitude_event.content_type,
        object_id=amplitude_event.object_id,
        event_timestamp=amplitude_event.event_timestamp,
    )
