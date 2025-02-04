from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from .models import FeedEntry
from .serializers import FeedEntrySerializer


class FeedPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class FeedViewSet(viewsets.ModelViewSet):
    serializer_class = FeedEntrySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedPagination

    def get_queryset(self):
        """Filter feed entries to show items related to what user follows"""
        action = self.request.query_params.get("action")
        content_type = self.request.query_params.get("content_type")

        following = self.request.user.following.all()

        queryset = (
            FeedEntry.objects.filter(
                parent_content_type_id__in=following.values("content_type"),
                parent_object_id__in=following.values("object_id"),
            )
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
            .order_by("-created_date")
        )
        if action:
            queryset = queryset.filter(action=action)
        if content_type:
            queryset = queryset.filter(content_type__model=content_type)

        return queryset
