import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from django.contrib.contenttypes.models import ContentType

from analytics.constants.event_types import (
    AMPLITUDE_TO_DB_EVENT_MAP,
    BULK_FEED_IMPRESSION,
    FEED_ITEM_IMPRESSION,
)
from user.models import User

logger = logging.getLogger(__name__)


def extract_related_work(event_props: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract related_work data from event_properties.

    Supports two formats:
    1. Nested: {"related_work": {"content_type": "...", "id": "...", ...}}
    2. Flat: {"related_work.content_type": "...", "related_work.id": "...", ...}

    Returns a dict with unified_document_id, content_type, and id if found,
    None otherwise.
    """
    # Check for nested format first
    related_work = event_props.get("related_work")
    if related_work and isinstance(related_work, dict):
        return {
            "unified_document_id": related_work.get("unified_document_id"),
            "content_type": related_work.get("content_type"),
            "id": related_work.get("id"),
        }

    # Check for flat format with dot notation
    flat_keys = {
        "unified_document_id": "related_work.unified_document_id",
        "content_type": "related_work.content_type",
        "id": "related_work.id",
    }

    flat_related_work = {}
    has_any_key = False
    for key, flat_key in flat_keys.items():
        value = event_props.get(flat_key)
        if value is not None:
            flat_related_work[key] = value
            has_any_key = True

    if has_any_key:
        return flat_related_work

    return None


@dataclass
class AmplitudeEvent:
    """
    Represents a parsed Amplitude event with fields for creating UserInteractions.

    Uses IDs rather than fetched objects to avoid unnecessary database queries.
    Validation happens at insert time via database constraints.
    """

    event_type: str
    unified_document_id: int
    event_timestamp: datetime
    user_id: Optional[int] = None
    external_user_id: Optional[str] = None
    content_type: Optional[ContentType] = None
    object_id: Optional[int] = None
    personalize_rec_id: Optional[str] = None
    impression: Optional[str] = None


class AmplitudeEventParser:
    """
    Parses raw Amplitude events into structured AmplitudeEvent objects.
    """

    _content_type_cache = {}

    def __init__(self):
        pass

    @classmethod
    def get_content_type(cls, model_name: str) -> ContentType:
        """Get ContentType with caching."""
        if model_name not in cls._content_type_cache:
            cls._content_type_cache[model_name] = ContentType.objects.get(
                model=model_name.lower()
            )
        return cls._content_type_cache[model_name]

    def _extract_user_ids(
        self, event: Dict[str, Any], validate_user_exists: bool = True
    ) -> Tuple[Optional[int], Optional[str]]:
        """Extract user_id and external_user_id from event."""
        event_props = event.get("event_properties", {})
        user_id_str = event_props.get("user_id") or event.get("user_id")
        external_user_id = event.get("amplitude_id") or event_props.get("amplitude_id")

        user_id = None
        if user_id_str:
            try:
                user_id = int(user_id_str)
                if validate_user_exists:
                    if not User.objects.filter(id=user_id).exists():
                        logger.warning(
                            f"User {user_id} not found, using external_user_id"
                        )
                        user_id = None
            except ValueError:
                logger.warning(f"Invalid user_id format: '{user_id_str}'")

        return user_id, external_user_id

    def _extract_timestamp(
        self, event: Dict[str, Any], time_field: str = "time"
    ) -> datetime:
        """Extract timestamp from event.

        Returns:
            Parsed datetime or current time if not available
        """
        timestamp_ms = event.get(time_field)
        if timestamp_ms:
            return datetime.fromtimestamp(timestamp_ms / 1000)
        return datetime.now()

    def parse_amplitude_event(self, event: Dict[str, Any]) -> Optional[AmplitudeEvent]:
        """Parse an Amplitude event and return an AmplitudeEvent object."""
        try:
            event_type = event.get("event_type", "").lower()
            event_props = event.get("event_properties", {})

            if event_type not in AMPLITUDE_TO_DB_EVENT_MAP:
                available_types = list(AMPLITUDE_TO_DB_EVENT_MAP.keys())
                logger.warning(
                    f"Event type '{event_type}' not in mapping. "
                    f"Available: {available_types}"
                )
                return None

            db_event_type = AMPLITUDE_TO_DB_EVENT_MAP[event_type]

            # Extract user identifiers
            user_id, external_user_id = self._extract_user_ids(event)

            if not user_id and not external_user_id:
                logger.warning(
                    f"No user_id or external_user_id for event '{event_type}'"
                )
                return None

            # Extract related work data
            related_work = extract_related_work(event_props)
            if not related_work:
                logger.warning(
                    f"No related_work data for event '{event_type}', "
                    f"user: {user_id or external_user_id}"
                )
                return None

            unified_doc_id = related_work.get("unified_document_id")
            content_type_str = related_work.get("content_type")
            object_id = related_work.get("id")

            # Get unified_document_id - either directly or via content_type lookup
            if unified_doc_id:
                try:
                    unified_doc_id = int(unified_doc_id)
                except ValueError:
                    logger.warning(f"Invalid unified_document_id: '{unified_doc_id}'")
                    return None

                if not content_type_str or not object_id:
                    logger.warning(
                        f"Missing content_type or object_id for "
                        f"unified_doc_id '{unified_doc_id}'"
                    )
                    return None

                try:
                    content_type = AmplitudeEventParser.get_content_type(
                        content_type_str
                    )
                    object_id = int(object_id)
                except (ContentType.DoesNotExist, ValueError) as e:
                    logger.warning(f"Invalid content_type/object_id: {e}")
                    return None
            elif content_type_str and object_id:
                try:
                    content_type = AmplitudeEventParser.get_content_type(
                        content_type_str
                    )
                    model_class = content_type.model_class()
                    object_id = int(object_id)
                    obj = model_class.objects.get(id=object_id)
                    unified_doc_id = obj.unified_document_id
                except (ContentType.DoesNotExist, ValueError, AttributeError) as e:
                    logger.warning(
                        f"Invalid content_type '{content_type_str}' or "
                        f"object_id '{object_id}': {e}"
                    )
                    return None
                except Exception as e:
                    logger.warning(f"Error looking up unified_document: {e}")
                    return None
            else:
                logger.warning(
                    "Neither unified_document_id nor content_type+id provided"
                )
                return None

            event_timestamp = self._extract_timestamp(event, "_time")

            # Extract optional fields
            recommendation_id = event_props.get("recommendation_id")
            personalize_rec_id = (
                str(recommendation_id) if recommendation_id is not None else None
            )

            impression = None
            impression_array = event_props.get("impression")
            if impression_array and isinstance(impression_array, list):
                impression = "|".join(str(item) for item in impression_array)

            return AmplitudeEvent(
                event_type=db_event_type,
                unified_document_id=unified_doc_id,
                event_timestamp=event_timestamp,
                user_id=user_id,
                external_user_id=external_user_id,
                content_type=content_type,
                object_id=object_id,
                personalize_rec_id=personalize_rec_id,
                impression=impression,
            )

        except Exception as e:
            event_type = event.get("event_type", "unknown")
            logger.error(f"Unexpected error parsing event '{event_type}': {e}")
            return None

    def parse_bulk_impression_event(
        self, event: Dict[str, Any]
    ) -> List[AmplitudeEvent]:
        """Parse a bulk_feed_impression event into multiple AmplitudeEvent objects.

        Args:
            event: Raw Amplitude event with impressions array

        Returns:
            List of AmplitudeEvent objects, one per impression.
            Invalid impressions are logged and skipped.
        """
        event_type = event.get("event_type", "").lower()
        if event_type != BULK_FEED_IMPRESSION:
            logger.warning(f"Expected bulk_feed_impression, got '{event_type}'")
            return []

        # Extract common fields
        user_id, external_user_id = self._extract_user_ids(event)

        if not user_id and not external_user_id:
            logger.warning("No user_id or external_user_id for bulk_feed_impression")
            return []

        event_timestamp = self._extract_timestamp(event, "time")

        # Extract impressions array
        event_props = event.get("event_properties", {})
        impressions = event_props.get("impressions", [])
        if not impressions:
            logger.warning(
                f"No impressions in bulk_feed_impression for "
                f"user {user_id or external_user_id}"
            )
            return []

        # Parse each impression - validation happens at insert time via FK constraint
        amplitude_events = []
        for impression_data in impressions:
            unified_doc_id = impression_data.get("unifiedDocumentId")
            recommendation_id = impression_data.get("recommendationId")

            if not unified_doc_id:
                logger.warning("Missing unifiedDocumentId in impression, skipping")
                continue

            try:
                unified_doc_id_int = int(unified_doc_id)
            except ValueError:
                logger.warning(f"Invalid unified_document_id: '{unified_doc_id}'")
                continue

            amplitude_events.append(
                AmplitudeEvent(
                    event_type=FEED_ITEM_IMPRESSION,
                    unified_document_id=unified_doc_id_int,
                    event_timestamp=event_timestamp,
                    user_id=user_id,
                    external_user_id=external_user_id,
                    personalize_rec_id=recommendation_id,
                )
            )

        return amplitude_events
