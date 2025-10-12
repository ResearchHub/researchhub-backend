"""
Base mapper class for event type mappers.

All event type mappers should inherit from BaseEventMapper and implement
the required abstract methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, List

from django.db.models import QuerySet


class BaseEventMapper(ABC):
    """Base class for all event type mappers."""

    @abstractmethod
    def get_queryset(self, start_date=None, end_date=None) -> QuerySet:
        """
        Get the queryset for this event type.

        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            QuerySet of records to process
        """
        pass

    @abstractmethod
    def map_to_interactions(self, record) -> List[Dict]:
        """
        Map a single record to one or more interaction dictionaries.

        Args:
            record: Database record (model instance)

        Returns:
            List of interaction dictionaries with Personalize schema
        """
        pass

    @property
    @abstractmethod
    def event_type_name(self) -> str:
        """Return the name of this event type."""
        pass
