from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Prefetch, Subquery
from rest_framework import status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from hub.models import Hub
from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument

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
        Filter feed entries based on the feed view ('following' or 'latest')
        and additional filters. For 'following' view, show items related to what
        user follows. For 'latest' view, show all items. Ensure that the result
        contains only the most recent entry per (content_type, object_id),
        ordered globally by the most recent action_date.
        """
        feed_view = self.request.query_params.get("feed_view", "latest")
        hub_slug = self.request.query_params.get("hub_slug")

        queryset = (
            FeedEntry.objects.all().select_related(
                "content_type",
                "parent_content_type",
                "user",
                "user__author_profile",
                "unified_document",
                "unified_document__paper",
            )
            # Prefetch related models for supported entities.
            # Must use `to_attr` to avoid shadowing the `item` field.
            # The serializer needs to access the `_prefetched_*` fields to
            # serialize the related models.
            .prefetch_related(
                "unified_document__hubs",
                Prefetch(
                    "item",
                    Bounty.objects.select_related("unified_document").prefetch_related(
                        "unified_document__hubs",
                    ),
                    to_attr="_prefetched_bounty",
                ),
                Prefetch(
                    "item",
                    Paper.objects.select_related("unified_document").prefetch_related(
                        "unified_document__hubs",
                        "authors",
                        "authors__user",
                    ),
                    to_attr="_prefetched_paper",
                ),
                Prefetch(
                    "item",
                    ResearchhubPost.objects.select_related(
                        "unified_document"
                    ).prefetch_related(
                        "unified_document__hubs",
                    ),
                    to_attr="_prefetched_post",
                ),
                Prefetch(
                    "item",
                    RhCommentModel.objects.prefetch_related(
                        "unified_document__hubs",
                    ),
                    to_attr="_prefetched_comment",
                ),
            )
        )

        # Apply following filter if feed_view is 'following' and user is authenticated
        if feed_view == "following" and self.request.user.is_authenticated:
            following = self.request.user.following.all()
            if following.exists():
                queryset = queryset.filter(
                    parent_content_type_id__in=following.values("content_type"),
                    parent_object_id__in=following.values("object_id"),
                )

        if feed_view == "popular":
            top_unified_docs = ResearchhubUnifiedDocument.objects.filter(
                is_removed=False
            ).order_by("-hot_score")

            # Apply any additional filters
            if hub_slug:
                try:
                    hub = Hub.objects.get(slug=hub_slug)
                except Hub.DoesNotExist:
                    return Response(
                        {"error": "Hub not found"}, status=status.HTTP_404_NOT_FOUND
                    )

                top_unified_docs = top_unified_docs.filter(hubs=hub)

            # Since there can be multiple feed entries per unified document,
            # we need to select the most recent entry for each document
            # Get the IDs of the most recent feed entry for each unified document
            latest_entries_subquery = (
                FeedEntry.objects.filter(unified_document__in=top_unified_docs)
                .values("unified_document")
                .annotate(
                    latest_id=models.Max("id"), latest_date=models.Max("action_date")
                )
                .values_list("latest_id", flat=True)
            )

            queryset = queryset.filter(
                id__in=Subquery(latest_entries_subquery), unified_document__isnull=False
            ).order_by("-unified_document__hot_score")

            return queryset

        # For other feed views (latest, following with hub filter)
        # Apply hub filter if hub_id is provided
        if hub_slug:
            try:
                hub = Hub.objects.get(slug=hub_slug)
            except Hub.DoesNotExist:
                return Response(
                    {"error": "Hub not found"}, status=status.HTTP_404_NOT_FOUND
                )

            hub_content_type = ContentType.objects.get_for_model(Hub)
            queryset = queryset.filter(
                parent_content_type=hub_content_type, parent_object_id=hub.id
            )

        sub_qs = queryset.order_by(
            "content_type_id", "object_id", "-action_date"
        ).distinct("content_type_id", "object_id")

        final_qs = queryset.filter(pk__in=sub_qs.values("pk")).order_by("-action_date")

        return final_qs
