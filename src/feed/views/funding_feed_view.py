"""
Specialized feed view focused on funding-related content for ResearchHub.
This view uses the Feed serializer on preregistration posts, instantiating
feed entries for each post instead of querying the feed table.
This is done for three reasons:
1. To provide a consistent endpoint for feed content.
2. Avoid filtering on feed entries which can be expensive since it is a large table.
3. Older feed entries are not in the feed table.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import (
    Case,
    DecimalField,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Cast
from rest_framework.response import Response

from feed.models import FeedEntry
from feed.serializers import FundingFeedEntrySerializer
from feed.views.base_feed_view import BaseFeedView
from purchase.models import Purchase
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from ..serializers import PostSerializer, serialize_feed_metrics
from .common import FeedPagination


class FundingFeedViewSet(BaseFeedView):
    """
    ViewSet for accessing entries specifically related to preregistration documents.
    This provides a dedicated endpoint for clients to fetch and display preregistration
    content in the Research Hub platform.

    Query Parameters:
    - fundraise_status: Filter by fundraise status
      Options:
        - OPEN: Only show posts with open fundraises
        - CLOSED: Only show posts with closed or completed fundraises
    """

    serializer_class = PostSerializer
    permission_classes = []
    pagination_class = FeedPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        page = request.query_params.get("page", "1")
        page_num = int(page)
        cache_key = self.get_cache_key(request, "funding")
        use_cache = page_num < 4

        if use_cache:
            # try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                if request.user.is_authenticated:
                    self.add_user_votes_to_response(request.user, cached_response)
                return Response(cached_response)

        # Get queryset
        queryset = self.get_queryset()

        # Get paginated posts
        page = self.paginate_queryset(queryset)

        feed_entries = []
        for post in page:
            # Create an unsaved FeedEntry instance
            feed_entry = FeedEntry(
                id=post.id,  # We can use the post ID as a temporary ID
                content_type=self._post_content_type,
                object_id=post.id,
                action="PUBLISH",
                action_date=post.created_date,
                user=post.created_by,
                unified_document=post.unified_document,
            )
            feed_entry.item = post
            metrics = serialize_feed_metrics(post, self._post_content_type)
            feed_entry.metrics = metrics
            feed_entries.append(feed_entry)

        serializer = FundingFeedEntrySerializer(feed_entries, many=True)
        response_data = self.get_paginated_response(serializer.data).data

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response_data)

        if use_cache:
            cache.set(cache_key, response_data, timeout=self.DEFAULT_CACHE_TIMEOUT)

        return Response(response_data)

    def get_queryset(self):
        """
        Filter to only include posts that are preregistrations.
        Additionally filter by fundraise status if specified.
        Uses database annotations to calculate amount raised and sort.
        """
        fundraise_status = self.request.query_params.get("fundraise_status", None)

        # Get content type for Fundraise model for GenericRelation
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)

        # Subquery to calculate total amount raised for each fundraise
        amount_raised_subquery = Subquery(
            Purchase.objects.filter(
                content_type=fundraise_content_type,
                object_id=OuterRef("unified_document__fundraises__id"),
            )
            .annotate(
                # Cast amount (which is a CharField) to Decimal first
                amount_decimal=Sum(
                    Cast(
                        "amount",
                        output_field=DecimalField(max_digits=19, decimal_places=10),
                    )
                )
            )
            .values("amount_decimal")[:1]
        )

        queryset = (
            ResearchhubPost.objects.all()
            .select_related(
                "created_by",
                "created_by__author_profile",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
                "unified_document__fundraises",
            )
            .filter(document_type=PREREGISTRATION)
            .filter(unified_document__is_removed=False)
        )

        if fundraise_status:
            if fundraise_status.upper() == "OPEN":
                queryset = queryset.filter(
                    unified_document__fundraises__status=Fundraise.OPEN
                )
            elif fundraise_status.upper() == "CLOSED":
                queryset = queryset.filter(
                    Q(unified_document__fundraises__status=Fundraise.CLOSED)
                    | Q(unified_document__fundraises__status=Fundraise.COMPLETED)
                )

        # Annotate with status priority
        # (0 for OPEN, 1 for CLOSED/COMPLETED, 2 for no fundraise)
        queryset = queryset.annotate(
            status_priority=Case(
                When(
                    unified_document__fundraises__status=Fundraise.OPEN, then=Value(0)
                ),
                When(
                    unified_document__fundraises__status=Fundraise.CLOSED, then=Value(1)
                ),
                When(
                    unified_document__fundraises__status=Fundraise.COMPLETED,
                    then=Value(1),
                ),
                default=Value(2),
                output_field=IntegerField(),
            ),
            amount_raised=Case(
                When(
                    unified_document__fundraises__isnull=False,
                    then=amount_raised_subquery,
                ),
                default=Value(0),
                output_field=DecimalField(max_digits=19, decimal_places=10),
            ),
        )

        # Order by status priority (OPEN first) and then by amount raised (descending)
        queryset = queryset.order_by("status_priority", "-amount_raised")

        return queryset
