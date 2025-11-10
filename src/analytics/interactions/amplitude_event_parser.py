import logging
from datetime import datetime
from typing import Any, Dict, Optional

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from analytics.constants.event_types import AMPLITUDE_TO_DB_EVENT_MAP
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

User = get_user_model()
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


class AmplitudeEvent:
    """
    Represents a parsed Amplitude event with all necessary fields for creating
    UserInteractions.

    This is a non-database model that holds pre-fetched Django model instances
    to avoid repeated database queries during mapping.
    """

    def __init__(
        self,
        user: Optional[User],
        event_type: str,
        unified_document: ResearchhubUnifiedDocument,
        content_type: ContentType,
        object_id: int,
        event_timestamp: datetime,
        session_id: Optional[str] = None,
    ):
        self.user = user
        self.session_id = session_id
        self.event_type = event_type
        self.unified_document = unified_document
        self.content_type = content_type
        self.object_id = object_id
        self.event_timestamp = event_timestamp


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

            user_id = event_props.get("user_id")
            session_id = event.get("amplitude_id") or event_props.get("amplitude_id")

            user = None
            if user_id:
                try:
                    user_id_int = int(user_id)
                    user = User.objects.get(id=user_id_int)
                except (ValueError, User.DoesNotExist) as e:
                    logger.warning(
                        f"Invalid user_id '{user_id}' for event_type "
                        f"'{event_type}': {e}. Continuing with session_id only."
                    )

            if not user and not session_id:
                logger.warning(
                    f"No user_id or session_id (amplitude_id) found for event_type "
                    f"'{event_type}'. Event: {event}"
                )
                return None

            related_work = extract_related_work(event_props)
            if not related_work:
                user_identifier = (
                    user_id
                    if user_id
                    else f"session_id:{session_id}" if session_id else "unknown"
                )
                logger.warning(
                    f"No related_work data found for event_type '{event_type}', "
                    f"user: '{user_identifier}'. Event: {event}"
                )
                return None

            unified_doc_id = related_work.get("unified_document_id")
            content_type_str = related_work.get("content_type")
            object_id = related_work.get("id")

            if unified_doc_id:
                try:
                    unified_doc_id = int(unified_doc_id)
                    unified_document = ResearchhubUnifiedDocument.objects.get(
                        id=unified_doc_id
                    )

                    if not content_type_str or not object_id:
                        logger.warning(
                            f"Missing content_type or object_id for "
                            f"unified_doc_id '{unified_doc_id}'. "
                            f"content_type: '{content_type_str}', "
                            f"object_id: '{object_id}'"
                        )
                        return None

                    content_type = AmplitudeEventParser.get_content_type(
                        content_type_str
                    )
                    object_id = int(object_id)
                except (
                    ValueError,
                    ResearchhubUnifiedDocument.DoesNotExist,
                    ContentType.DoesNotExist,
                ) as e:
                    logger.warning(
                        f"Invalid unified_document_id '{unified_doc_id}' "
                        f"or related data: {e}"
                    )
                    return None
            elif content_type_str and object_id:
                try:
                    content_type = AmplitudeEventParser.get_content_type(
                        content_type_str
                    )
                    model_class = content_type.model_class()
                    object_id = int(object_id)
                    obj = model_class.objects.get(id=object_id)
                    unified_document = obj.unified_document
                except ContentType.DoesNotExist as e:
                    logger.warning(f"Invalid content_type '{content_type_str}': {e}")
                    return None
                except (ValueError, AttributeError) as e:
                    logger.warning(
                        f"Invalid content_type '{content_type_str}' or "
                        f"object_id '{object_id}': {e}"
                    )
                    return None
                except Exception as e:
                    logger.warning(
                        f"Invalid content_type '{content_type_str}' or "
                        f"object_id '{object_id}': {e}"
                    )
                    return None
            else:
                logger.warning(
                    f"Neither unified_document_id nor content_type+id provided. "
                    f"unified_doc_id: '{unified_doc_id}', "
                    f"content_type: '{content_type_str}', id: '{object_id}'"
                )
                return None

            timestamp_ms = event.get("_time")
            if timestamp_ms:
                event_timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                event_timestamp = datetime.now()

            amplitude_event = AmplitudeEvent(
                user=user,
                event_type=db_event_type,
                unified_document=unified_document,
                content_type=content_type,
                object_id=object_id,
                event_timestamp=event_timestamp,
                session_id=session_id,
            )

            return amplitude_event

        except Exception as e:
            event_type = event.get("event_type", "unknown")
            logger.error(f"Unexpected error parsing event '{event_type}': {e}")
            return None
