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


class AmplitudeEvent:
    """
    Represents a parsed Amplitude event with all necessary fields for creating
    UserInteractions.

    This is a non-database model that holds pre-fetched Django model instances
    to avoid repeated database queries during mapping.
    """

    def __init__(
        self,
        user: User,
        event_type: str,
        unified_document: ResearchhubUnifiedDocument,
        content_type: ContentType,
        object_id: int,
        event_timestamp: datetime,
    ):
        self.user = user
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
                return None

            db_event_type = AMPLITUDE_TO_DB_EVENT_MAP[event_type]

            user_id = event_props.get("user_id")
            if not user_id:
                return None

            try:
                user_id = int(user_id)
                user = User.objects.get(id=user_id)
            except (ValueError, User.DoesNotExist):
                return None

            related_work = event_props.get("related_work", {})
            if not related_work:
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
                        return None

                    content_type = AmplitudeEventParser.get_content_type(
                        content_type_str
                    )
                    object_id = int(object_id)
                except (ValueError, ResearchhubUnifiedDocument.DoesNotExist):
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
                except (
                    ValueError,
                    ContentType.DoesNotExist,
                    model_class.DoesNotExist,
                    AttributeError,
                ):
                    return None
            else:
                return None

            timestamp_ms = event.get("time")
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
            )

            return amplitude_event

        except Exception:
            return None
