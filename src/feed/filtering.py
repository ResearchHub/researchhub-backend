import logging
from typing import List

from rest_framework.filters import BaseFilterBackend

from feed.feed_config import FEED_CONFIG
from feed.models import FeedEntry
from hub.models import Hub
from personalize.config.settings import PERSONALIZE_CONFIG
from personalize.services.feed_service import DEFAULT_NUM_RESULTS
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from utils.sentry import log_error

logger = logging.getLogger(__name__)


class FeedFilteringBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        feed_view = request.query_params.get("feed_view", "popular")

        if feed_view == "following":
            return self._filter_following(request, queryset, view)
        elif feed_view == "personalized":
            return self._filter_personalized(request, queryset, view)
        elif feed_view == "latest":
            return self._filter_latest(request, queryset, view)
        else:
            return self._filter_popular(request, queryset, view)

    def _filter_latest(self, request, queryset, view):
        hub_slug = request.query_params.get("hub_slug")
        if hub_slug:
            queryset = self._filter_by_hub(hub_slug, queryset)

        queryset = queryset.filter(
            content_type__in=[view._paper_content_type, view._post_content_type]
        )

        return queryset

    def _filter_following(self, request, queryset, view):
        if not request.user.is_authenticated:
            return queryset.none()

        followed_hub_ids = view.get_followed_hub_ids()
        if followed_hub_ids:
            queryset = queryset.filter(hubs__id__in=followed_hub_ids)
        else:
            return queryset.none()

        hub_slug = request.query_params.get("hub_slug")
        if hub_slug:
            queryset = self._filter_by_hub(hub_slug, queryset)

        queryset = queryset.filter(content_type=view._paper_content_type)

        return queryset

    def _filter_popular(self, request, queryset, view):
        hub_slug = request.query_params.get("hub_slug")
        if hub_slug:
            queryset = self._filter_by_hub(hub_slug, queryset)

        queryset = queryset.filter(
            content_type__in=[view._paper_content_type, view._post_content_type]
        )

        ordering = request.query_params.get("ordering")
        allowed_sorts = FEED_CONFIG.get("popular", {}).get("allowed_sorts", [])
        default = allowed_sorts[0] if allowed_sorts else None
        effective_ordering = ordering if ordering in allowed_sorts else default

        if effective_ordering == "aws_trending":
            return self._filter_popular_with_aws_trending(request, queryset, view)

        # For hot_score or hot_score_v2, return queryset for ordering backend to handle
        view._feed_source = "researchhub"
        return queryset

    def _filter_popular_with_aws_trending(self, request, queryset, view):
        """
        Fetch trending IDs from AWS Personalize and return sorted entries.
        Falls back to queryset ordering on failure.
        """
        personalize_feed_service = getattr(view, "personalize_feed_service", None)
        if not personalize_feed_service:
            logger.warning("personalize_feed_service not available, using fallback")
            view._feed_source = "researchhub"
            return queryset

        filter_param = request.query_params.get("filter", None)

        try:
            result = personalize_feed_service.get_trending_ids(
                filter_param=filter_param,
                num_results=PERSONALIZE_CONFIG.get(
                    "trending_num_results", DEFAULT_NUM_RESULTS
                ),
            )

            trending_ids = result.get("item_ids", [])

            if not trending_ids:
                logger.warning("No trending IDs returned, using fallback")
                view._feed_source = "researchhub"
                return queryset

            view._feed_source = "aws"

            return self._fetch_and_order_entries_for_trending(
                trending_ids, queryset, view
            )

        except Exception as e:
            log_error(
                e,
                message="AWS Personalize trending failed, falling back to hot_score_v2",
                json_data={"feed_view": "popular", "ordering": "aws_trending"},
            )
            logger.error(f"Trending feed error: {e}")
            view._feed_source = "researchhub"
            return queryset

    def _fetch_and_order_entries_for_trending(
        self, document_ids: List[int], queryset, view
    ) -> List[FeedEntry]:
        """
        Fetch and order entries based on trending document IDs.
        Filters by the documents in the trending list and sorts in-memory.
        Excludes PREREGISTRATION documents from results.
        """
        position_map = {pk: pos for pos, pk in enumerate(document_ids)}

        # Apply the document ID filter while preserving other queryset filters
        # Exclude PREREGISTRATION documents from trending results
        entries = list(
            queryset.filter(
                unified_document_id__in=document_ids,
            ).exclude(
                unified_document__document_type=PREREGISTRATION,
            )
        )

        entries.sort(
            key=lambda entry: position_map.get(entry.unified_document_id, float("inf"))
        )

        return entries

    def _filter_personalized(self, request, queryset, view):
        user_id = request.query_params.get("user_id")
        if user_id:
            user_id = int(user_id)
        elif request.user.is_authenticated:
            user_id = request.user.id
        else:
            return queryset

        personalize_feed_service = getattr(view, "personalize_feed_service", None)
        if not personalize_feed_service:
            return queryset

        filter_param = request.query_params.get("filter", None)
        force_refresh_header = request.META.get("HTTP_RH_FORCE_REFRESH", "false")
        force_refresh = force_refresh_header.lower() == "true"

        try:
            result = personalize_feed_service.get_recommendation_ids(
                user_id=user_id,
                filter_param=filter_param,
                num_results=PERSONALIZE_CONFIG["num_results"],
                force_refresh=force_refresh,
            )

            recommended_ids = result.get("item_ids", [])
            view._personalize_recommendation_id = result.get("recommendation_id")

            if not recommended_ids:
                return queryset.none()

            return self._fetch_and_order_entries(recommended_ids, view)

        except Exception as e:
            logger.error(f"Personalized feed error for user {user_id}: {e}")
            return queryset.none()

    def _fetch_and_order_entries(
        self, document_ids: List[int], view
    ) -> List[FeedEntry]:
        position_map = {pk: pos for pos, pk in enumerate(document_ids)}

        entries = list(
            FeedEntry.objects.filter(
                unified_document_id__in=document_ids,
                content_type=view._paper_content_type,
            ).select_related(
                "content_type",
                "user",
                "user__author_profile",
                "user__userverification",
            )
        )

        entries.sort(
            key=lambda entry: position_map.get(entry.unified_document_id, float("inf"))
        )

        return entries

    def _filter_by_hub(self, hub_slug, queryset):
        try:
            hub = Hub.objects.get(slug=hub_slug)
        except Hub.DoesNotExist:
            return queryset.none()

        return queryset.filter(hubs__in=[hub])
