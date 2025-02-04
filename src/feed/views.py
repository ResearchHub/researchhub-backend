from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination

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
        """Filter feed entries to show items related to what user follows, or all items if no follows"""
        action = self.request.query_params.get("action")
        content_type = self.request.query_params.get("content_type")

        # Base queryset with all necessary joins
        queryset = (
            FeedEntry.objects.all()
            .select_related(
                "content_type",
                "parent_content_type",
                "user",
                "user__author_profile",
            )
            .prefetch_related(
                "item__authors",
                "item__hubs",
            )
            # Order first by the distinct columns, then by action_date
            .order_by("content_type", "object_id", "-action_date")
            .distinct("content_type", "object_id")
        )

        # Apply following filter only if user is authenticated and has follows
        if self.request.user.is_authenticated:
            following = self.request.user.following.all()
            if following.exists():  # Only filter if user is following something
                queryset = queryset.filter(
                    parent_content_type_id__in=following.values("content_type"),
                    parent_object_id__in=following.values("object_id"),
                )

        # Apply additional filters
        if action:
            queryset = queryset.filter(action=action)
        if content_type:
            queryset = queryset.filter(content_type__model=content_type)

        return queryset
