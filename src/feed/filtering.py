import logging
from typing import List

from rest_framework.filters import BaseFilterBackend

from feed.models import FeedEntry
from hub.models import Hub
from personalize.config.settings import PERSONALIZE_CONFIG

logger = logging.getLogger(__name__)


class FeedFilteringBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        feed_view = request.query_params.get("feed_view", "popular")

        if feed_view == "following":
            return self._filter_following(request, queryset, view)
        elif feed_view == "personalized":
            return self._filter_personalized(request, queryset, view)
        else:
            return self._filter_popular(request, queryset, view)

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

        return queryset

    def _filter_popular(self, request, queryset, view):
        hub_slug = request.query_params.get("hub_slug")
        if hub_slug:
            queryset = self._filter_by_hub(hub_slug, queryset)

        return queryset

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
            recommended_ids = personalize_feed_service.get_recommendation_ids(
                user_id=user_id,
                filter_param=filter_param,
                num_results=PERSONALIZE_CONFIG["num_results"],
                force_refresh=force_refresh,
            )

            if not recommended_ids:
                return queryset.none()

            return self._fetch_and_order_entries(recommended_ids)

        except Exception as e:
            logger.error(f"Personalized feed error for user {user_id}: {e}")
            return queryset.none()

    def _fetch_and_order_entries(self, document_ids: List[int]) -> List[FeedEntry]:
        position_map = {pk: pos for pos, pk in enumerate(document_ids)}

        entries = list(
            FeedEntry.objects.filter(
                unified_document_id__in=document_ids
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
