"""
Shared utility functions for Personalize export.

This module contains helper functions used across different event mappers.
"""

from datetime import datetime
from typing import Dict, List, Optional

from django.contrib.contenttypes.models import ContentType


def get_unified_document_id(content_type: ContentType, object_id: int) -> Optional[int]:
    """
    Extract unified document ID from content type and object ID.

    Args:
        content_type: Django ContentType instance
        object_id: ID of the object

    Returns:
        Unified document ID or None if unable to extract
    """
    try:
        model_class = content_type.model_class()
        if model_class is None:
            return None

        obj = model_class.objects.get(id=object_id)

        # Handle different content types based on unified documents
        model_name = content_type.model.lower()

        if model_name in ["paper", "researchhubpost", "bounty"]:
            # These models have direct unified_document foreign key
            if hasattr(obj, "unified_document") and obj.unified_document:
                return obj.unified_document.id

        elif model_name == "rhcommentmodel":
            # Comments link to unified document through thread
            if hasattr(obj, "thread") and obj.thread:
                thread_unified_doc = obj.thread.unified_document
                if hasattr(obj.thread, "unified_document") and thread_unified_doc:
                    return obj.thread.unified_document.id

        return None

    except Exception:
        # If object doesn't exist or any other error, return None
        return None


def datetime_to_epoch_seconds(dt: datetime) -> int:
    """
    Convert datetime to Unix epoch timestamp in seconds.

    Args:
        dt: datetime object

    Returns:
        Unix epoch timestamp as integer (seconds since 1970-01-01)
    """
    return int(dt.timestamp())


def format_interaction_csv_row(interaction: Dict) -> List:
    """
    Format an interaction dictionary to a CSV row.

    Args:
        interaction: Interaction dictionary with Personalize schema fields

    Returns:
        List of values in the correct order for CSV export
    """
    return [
        interaction["USER_ID"],
        interaction["ITEM_ID"],
        interaction["EVENT_TYPE"],
        interaction["EVENT_VALUE"],
        interaction["DEVICE"] if interaction["DEVICE"] is not None else "",
        interaction["TIMESTAMP"],
        (interaction["IMPRESSION"] if interaction["IMPRESSION"] is not None else ""),
        (
            interaction["RECOMMENDATION_ID"]
            if interaction["RECOMMENDATION_ID"] is not None
            else ""
        ),
    ]
