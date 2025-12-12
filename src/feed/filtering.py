import logging
from typing import List, Tuple

from django.core.cache import cache
from rest_framework.filters import BaseFilterBackend

from feed.feed_config import FEED_CONFIG
from feed.models import FeedEntry
from hub.models import Hub
from personalize.config.settings import PERSONALIZE_CONFIG
from personalize.services.feed_service import DEFAULT_NUM_RESULTS
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from utils.sentry import log_error

logger = logging.getLogger(__name__)

# Allowed preprint hub slugs for feed filtering
ALLOWED_PREPRINT_HUB_SLUGS = frozenset({"biorxiv", "arxiv", "chemrxiv", "medrxiv"})
PREPRINT_HUB_IDS_CACHE_KEY = "feed:allowed_preprint_hub_ids"
PREPRINT_HUB_IDS_CACHE_TTL = 86400  # 24 hours


def _get_allowed_preprint_hub_ids() -> Tuple[int, ...]:
    """
    Get cached hub IDs for allowed preprint sources.
    """
    hub_ids = cache.get(PREPRINT_HUB_IDS_CACHE_KEY)
    if hub_ids is None:
        hub_ids = tuple(
            Hub.objects.filter(slug__in=ALLOWED_PREPRINT_HUB_SLUGS).values_list(
                "id", flat=True
            )
        )
        cache.set(
            PREPRINT_HUB_IDS_CACHE_KEY, hub_ids, timeout=PREPRINT_HUB_IDS_CACHE_TTL
        )
    return hub_ids


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
            # When hub_slug is specified, filter by that hub (papers only)
            queryset = self._filter_by_hub(hub_slug, queryset)
            queryset = queryset.filter(content_type=view._paper_content_type)
        else:
            # No hub specified - restrict to allowed preprint hubs
            queryset = self._filter_by_allowed_preprint_hubs(queryset, view)

        return queryset

    def _filter_following(self, request, queryset, view):
        if not request.user.is_authenticated:
            return queryset.none()

        followed_hub_ids = view.get_followed_hub_ids()
        if followed_hub_ids:
            queryset = queryset.filter(hubs__id__in=followed_hub_ids)
        else:
            return queryset.none()

        # Require papers to be in an allowed preprint hub
        preprint_hub_ids = _get_allowed_preprint_hub_ids()
        queryset = queryset.filter(
            content_type=view._paper_content_type,
            hubs__id__in=preprint_hub_ids,
        )

        return queryset

    def _filter_popular(self, request, queryset, view):
        hub_slug = request.query_params.get("hub_slug")
        if hub_slug:
            # When hub_slug is specified, filter by that hub (papers only)
            queryset = self._filter_by_hub(hub_slug, queryset)
            queryset = queryset.filter(content_type=view._paper_content_type)
        else:
            # No hub specified - restrict to allowed preprint hubs
            queryset = self._filter_by_allowed_preprint_hubs(queryset, view)

        ordering = request.query_params.get("ordering")
        allowed_sorts = FEED_CONFIG.get("popular", {}).get("allowed_sorts", [])
        default = allowed_sorts[0] if allowed_sorts else None
        effective_ordering = ordering if ordering in allowed_sorts else default

        if effective_ordering == "aws_trending":
            return self._filter_popular_with_aws_trending(request, queryset, view)

        # For hot_score or hot_score_v2, return queryset for ordering backend to handle
        view._feed_source = "rh-popular"
        return queryset

    def _filter_popular_with_aws_trending(self, request, queryset, view):
        """
        Fetch trending IDs from AWS Personalize and return sorted entries.
        Falls back to queryset ordering on failure.
        """
        personalize_feed_service = getattr(view, "personalize_feed_service", None)
        if not personalize_feed_service:
            logger.warning("personalize_feed_service not available, using fallback")
            view._feed_source = "rh-popular"
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
                view._feed_source = "rh-popular"
                return queryset

            view._feed_source = "aws-trending"

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
            view._feed_source = "rh-popular"
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
        """
        Personalized recommendations or fallback to following feed.
        """
        if not request.user.is_authenticated:
            return queryset.none()

        user_id = request.user.id

        personalize_feed_service = getattr(view, "personalize_feed_service", None)
        if not personalize_feed_service:
            # Fallback to following if Personalize unavailable
            view._feed_source = "rh-following"
            return self._filter_following(request, queryset, view)

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
                # Fallback to following if no recommendations
                view._feed_source = "rh-following"
                return self._filter_following(request, queryset, view)

            view._feed_source = "aws-personalize"
            return self._fetch_and_order_entries(recommended_ids, view)

        except Exception as e:
            logger.error(f"Personalized feed error for user {user_id}: {e}")
            # Fallback to following on error
            view._feed_source = "rh-following"
            return self._filter_following(request, queryset, view)

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

    def _filter_by_allowed_preprint_hubs(self, queryset, view):
        """
        Filter queryset to only include papers from allowed preprint hubs.
        Papers must have at least one hub from: biorxiv, arxiv, chemrxiv, medrxiv.
        """
        preprint_hub_ids = _get_allowed_preprint_hub_ids()
        return queryset.filter(
            content_type=view._paper_content_type,
            hubs__id__in=preprint_hub_ids,
        )

    def _filter_by_hub(self, hub_slug, queryset):
        try:
            hub = Hub.objects.get(slug=hub_slug)
        except Hub.DoesNotExist:
            return queryset.none()

        return queryset.filter(hubs__in=[hub])
