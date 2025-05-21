"""
Specialized feed view focused on papers published in the ResearchHub journal.
This view returns papers based on their PaperVersion journal status and
allows filtering by publication status (PREPRINT or PUBLISHED).
"""

from django.core.cache import cache
from django.db.models import OuterRef, Subquery
from rest_framework.response import Response

from feed.models import FeedEntry
from feed.serializers import FeedEntrySerializer
from feed.views.base_feed_view import BaseFeedView
from paper.related_models.paper_model import Paper, PaperVersion

from ..serializers import serialize_feed_metrics
from .common import FeedPagination


class JournalFeedViewSet(BaseFeedView):
    """
    ViewSet for accessing papers published in the ResearchHub journal.
    Provides a dedicated endpoint for clients to fetch and display journal papers.

    Query Parameters:
    - publication_status: Filter by publication status
      Options:
        - PREPRINT: Only show preprints
        - PUBLISHED: Only show published papers
        - ALL: Show all papers (default)
    """

    serializer_class = FeedEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = self.get_cache_key(request, "journal")
        use_cache = page_num < 4

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        # Get paginated papers
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        feed_entries = []
        for paper in page:
            # Create an unsaved FeedEntry instance
            feed_entry = FeedEntry(
                id=paper.id,  # Use the paper ID as a temporary ID
                content_type=self._paper_content_type,
                object_id=paper.id,
                action="PUBLISH",
                action_date=paper.created_date,
                user=paper.uploaded_by,
                unified_document=paper.unified_document,
            )
            feed_entry.item = paper
            metrics = serialize_feed_metrics(paper, self._paper_content_type)
            feed_entry.metrics = metrics
            feed_entries.append(feed_entry)

        serializer = self.get_serializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        if use_cache:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def get_queryset(self):
        """
        Filter to only include papers published in the ResearchHub journal.
        Additionally filter by publication status if specified.
        Returns only one paper per base_doi.
        """
        publication_status = self.request.query_params.get("publication_status", "ALL")

        # Get latest paper per base_doi
        latest_versions = (
            PaperVersion.objects.filter(base_doi=OuterRef("version__base_doi"))
            .order_by("-created_date")
            .values("paper_id")[:1]
        )

        queryset = (
            Paper.objects.all()
            .select_related(
                "uploaded_by",
                "uploaded_by__author_profile",
                "unified_document",
                "version",
            )
            .prefetch_related(
                "unified_document__hubs",
            )
            .filter(version__journal=PaperVersion.RESEARCHHUB)
            .filter(
                is_removed=False,
                is_removed_by_user=False,
                is_public=True,
            )
            # Only include papers where the version's base_doi is not null
            .filter(version__base_doi__isnull=False)
            # Use a subquery to only include the latest paper per base_doi
            .filter(id=Subquery(latest_versions))
        )

        # Apply publication status filter
        if publication_status.upper() == "PREPRINT":
            queryset = queryset.filter(
                version__publication_status=PaperVersion.PREPRINT
            )
        elif publication_status.upper() == "PUBLISHED":
            queryset = queryset.filter(
                version__publication_status=PaperVersion.PUBLISHED
            )

        queryset = queryset.order_by("-created_date")

        return queryset
