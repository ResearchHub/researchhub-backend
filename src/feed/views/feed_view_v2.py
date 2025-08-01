from django_elasticsearch_dsl_drf.filter_backends import (
    DefaultOrderingFilterBackend,
    FilteringFilterBackend,
    OrderingFilterBackend,
    SearchFilterBackend,
)
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Q

from feed.document_serializers.feed_document_serializer import (
    FeedEntryDocumentSerializer,
)
from feed.documents.feed_document import FeedEntryDocument
from feed.views.common import FeedPagination
from feed.views.feed_view_mixin import FeedViewMixin


class FeedV2ViewSet(FeedViewMixin, DocumentViewSet):
    """
    ViewSet for accessing the main feed of ResearchHub activities using Elasticsearch.
    Supports filtering by hub, following status, source, and sorting by popularity.
    """

    document = FeedEntryDocument
    permission_classes = []
    serializer_class = FeedEntryDocumentSerializer
    pagination_class = FeedPagination

    filter_backends = [
        FilteringFilterBackend,
        OrderingFilterBackend,
        DefaultOrderingFilterBackend,
        SearchFilterBackend,
    ]

    filter_fields = {
        "hub": "hubs.slug",
    }

    ordering_fields = {
        "action_date": "action_date",
        "hot_score": "hot_score",
        "created_date": "created_date",
    }

    ordering = ("-action_date",)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        return response

    def get_queryset(self):
        """
        Filter feed entries based on the feed view ('following' or 'latest')
        and additional filters. For 'following' view, show items related to what
        user follows. For 'latest' view, show all items.
        """
        queryset = super().get_queryset()

        feed_view = self.request.query_params.get("feed_view", "latest")
        hub_slug = self.request.query_params.get("hub_slug")
        source = self.request.query_params.get("source", "all")

        query = Q()

        # Apply source filter
        # If source is 'researchhub', then only show items that are related to
        # ResearchHub content. Since we don't have a dedicated field for this,
        # a simplified heuristic is to filter out papers (papers are ingested via
        # OpenAlex and do not originate on ResearchHub).
        if source == "researchhub":
            query &= ~Q("term", **{"content_type.id": self._paper_content_type.id})

        if hub_slug:
            query &= Q(
                "nested", path="hubs", query=Q("term", **{"hubs.slug": hub_slug})
            )

        # Apply following filter
        if feed_view == "following":
            followed_hub_ids = self.get_followed_hub_ids()
            if followed_hub_ids:
                query &= Q(
                    "nested",
                    path="hubs",
                    query=Q("terms", **{"hubs.id": list(followed_hub_ids)}),
                )

        if feed_view == "popular":
            # Only show papers and posts
            query &= Q(
                "terms",
                **{
                    "content_type.id": [
                        self._paper_content_type.id,
                        self._post_content_type.id,
                    ]
                },
            )

        # Apply query
        if query:
            queryset = queryset.query(query)

        # Apply ordering based on feed view
        match feed_view:
            case "popular":
                queryset = queryset.sort("-hot_score")
            case "latest" | "following":
                queryset = queryset.sort("-action_date")

        return queryset
