"""
Shared utility functions for AWS Personalize data export.
"""

from datetime import datetime
from typing import Optional


def datetime_to_epoch_seconds(dt: Optional[datetime]) -> Optional[int]:
    """
    Convert a datetime to Unix epoch seconds.

    Args:
        dt: Datetime object (can be timezone-aware or naive)

    Returns:
        Unix timestamp as integer, or None if dt is None
    """
    if dt is None:
        return None

    return int(dt.timestamp())
