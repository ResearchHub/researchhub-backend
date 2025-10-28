from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from django.db.models import QuerySet

from analytics.models import UserInteractions


class BaseInteractionMapper(ABC):
    """
    Abstract base class for mapping source records to UserInteractions.
    """

    @abstractmethod
    def map_to_interaction(self, record) -> UserInteractions:
        """
        Convert a source record to a UserInteractions instance.
        """
        pass

    @abstractmethod
    def get_queryset(
        self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> QuerySet:
        """
        Get filtered queryset of source records.
        """
        pass

    @property
    @abstractmethod
    def event_type_name(self) -> str:
        """
        Get the event type constant for this mapper.

        Returns:
            Event type constant from analytics.constants.event_types
            (e.g., UPVOTE, ..)
        """
        pass
