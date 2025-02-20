from django.db.models import F, Prefetch, Window
from django.db.models.functions import RowNumber
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination

from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty

from .models import FeedEntry
from .serializers import FeedEntrySerializer


class FeedPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class FeedViewSet(viewsets.ModelViewSet):
    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_queryset(self):
        """
        Filter feed entries to show items related to what user follows,
        or all items if no follows, and ensure that the result contains
        only the most recent entry per (content_type, object_id), ordered
        globally by the most recent action_date.
        """
        action = self.request.query_params.get("action")
        content_type = self.request.query_params.get("content_type")

        queryset = (
            FeedEntry.objects.all().select_related(
                "content_type",
                "parent_content_type",
                "user",
                "user__author_profile",
            )
            # Prefetch related models for supported entities (bounty, paper).
            # Must use `to_attr` to avoid shadowing the `item` field.
            # The serializer needs to access the `_prefetched_*` fields to
            # serialize the related models.
            .prefetch_related(
                Prefetch(
                    "item",
                    Bounty.objects.prefetch_related(
                        "unified_document",
                        "unified_document__hubs",
                        "unified_document__paper",
                    ),
                    to_attr="_prefetched_bounty",
                ),
                Prefetch(
                    "item",
                    Paper.objects.prefetch_related(
                        "unified_document",
                        "unified_document__hubs",
                        "authors",
                        "authors__user",
                    ),
                    to_attr="_prefetched_paper",
                ),
            )
        )

        # Apply following filter only if the user is authenticated and has follows.
        if self.request.user.is_authenticated:
            following = self.request.user.following.all()
            if following.exists():
                queryset = queryset.filter(
                    parent_content_type_id__in=following.values("content_type"),
                    parent_object_id__in=following.values("object_id"),
                )

        # Apply additional filters.
        if action:
            queryset = queryset.filter(action=action)
        if content_type:
            queryset = queryset.filter(content_type__model=content_type)

        # Use a window function to partition by 'content_type' and 'object_id',
        # ordering each partition by action_date in descending order.
        # The first row (row_number == 1) in each partition will then
        # be the latest record.
        queryset = (
            queryset.annotate(
                row_number=Window(
                    expression=RowNumber(),
                    partition_by=[F("content_type"), F("object_id")],
                    order_by=F("action_date").desc(),
                )
            )
            .filter(row_number=1)
            .order_by("-action_date")
        )

        return queryset
