import logging
from datetime import datetime
from typing import Dict, Optional

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from analytics.interactions.constants import AMPLITUDE_TO_DB_EVENT_MAP
from analytics.models import UserInteractions
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class AmplitudeEventMapper:
    """
    Maps raw Amplitude events to UserInteractions model instances.

    Unlike other interaction mappers that work with Django QuerySets,
    this mapper works directly with raw event dictionaries from Amplitude webhooks.
    """

    # Class-level cache shared across all instances
    _content_type_cache = {}

    def __init__(self):
        # No instance-level cache needed - using class-level cache
        pass

    @classmethod
    def get_content_type(cls, model_name: str) -> ContentType:
        """Get ContentType with class-level caching to avoid repeated DB queries."""
        if model_name not in cls._content_type_cache:
            cls._content_type_cache[model_name] = ContentType.objects.get(
                model=model_name.lower()
            )
        return cls._content_type_cache[model_name]

    def map_amplitude_event_to_interaction(
        self, event: Dict
    ) -> Optional[UserInteractions]:
        """
        Convert an Amplitude event to a UserInteractions instance.

        Args:
            event: Raw event dictionary from Amplitude webhook

        Returns:
            UserInteractions instance (unsaved) or None if event is invalid
        """
        try:
            # Extract basic event data
            event_type = event.get("event_type", "").lower()
            event_props = event.get("event_properties", {})

            # Validate event type
            if event_type not in AMPLITUDE_TO_DB_EVENT_MAP:
                return None

            db_event_type = AMPLITUDE_TO_DB_EVENT_MAP[event_type]

            # Extract user_id
            user_id = event_props.get("user_id")
            if not user_id:
                return None

            try:
                # Convert to int in case it's passed as string
                user_id = int(user_id)
                user = User.objects.get(id=user_id)
            except (ValueError, User.DoesNotExist):
                return None

            # Extract related work data
            related_work = event_props.get("related_work", {})
            if not related_work:
                return None

            # Get unified_document_id or construct from content_type + id
            unified_doc_id = related_work.get("unified_document_id")
            content_type_str = related_work.get("content_type")
            object_id = related_work.get("id")

            if unified_doc_id:
                try:
                    # Convert to int in case it's passed as string
                    unified_doc_id = int(unified_doc_id)
                    unified_document = ResearchhubUnifiedDocument.objects.get(
                        id=unified_doc_id
                    )

                    if not content_type_str or not object_id:
                        return None

                    content_type = AmplitudeEventMapper.get_content_type(
                        content_type_str
                    )
                    object_id = int(object_id)
                except (ValueError, ResearchhubUnifiedDocument.DoesNotExist):
                    return None
            elif content_type_str and object_id:
                # Construct item_id from content_type and id
                try:
                    content_type = AmplitudeEventMapper.get_content_type(
                        content_type_str
                    )
                    # Get the actual object to find its unified_document
                    model_class = content_type.model_class()
                    # Convert to int in case it's passed as string
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

            # Convert timestamp from milliseconds to datetime
            timestamp_ms = event.get("time")
            if timestamp_ms:
                event_timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                event_timestamp = datetime.now()

            # Create UserInteractions instance using get_or_create to handle duplicates
            interaction, created = UserInteractions.objects.get_or_create(
                user=user,
                event=db_event_type,
                unified_document=unified_document,
                content_type=content_type,
                object_id=object_id,
                defaults={
                    "event_timestamp": event_timestamp,
                    "is_synced_with_personalize": False,
                    "personalize_rec_id": None,
                },
            )

            return interaction

        except Exception:
            # Return None for any unexpected errors during mapping
            return None
