from datetime import datetime
from typing import Optional

from django.db.models import QuerySet

from analytics.constants.event_types import UPVOTE
from analytics.interactions.base_interaction_mapper import BaseInteractionMapper
from analytics.models import UserInteractions
from discussion.models import Vote


class UpvoteInteractionMapper(BaseInteractionMapper):
    """
    Maps Vote records (upvotes) to UserInteractions.
    """

    @property
    def event_type_name(self) -> str:
        return UPVOTE

    def get_queryset(
        self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> QuerySet:
        queryset = Vote.objects.select_related("created_by").filter(
            vote_type=Vote.UPVOTE
        )

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interaction(self, record: Vote) -> UserInteractions:
        return UserInteractions(
            user=record.created_by,
            event=self.event_type_name,
            unified_document=record.unified_document,
            content_type=record.content_type,
            object_id=record.object_id,
            event_timestamp=record.created_date,
            is_synced_with_personalize=False,
            personalize_rec_id=None,
        )
