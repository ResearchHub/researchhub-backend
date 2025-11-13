from rest_framework.filters import BaseFilterBackend

from feed.feed_config import PERSONALIZE_CONFIG
from hub.models import Hub


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
        force_new_param = request.query_params.get("force-new-recs", "false")
        force_refresh = force_new_param.lower() == "true"

        return personalize_feed_service.get_feed_queryset(
            user_id=user_id,
            filter_param=filter_param,
            num_results=PERSONALIZE_CONFIG["num_results"],
            force_refresh=force_refresh,
        )

    def _filter_by_hub(self, hub_slug, queryset):
        try:
            hub = Hub.objects.get(slug=hub_slug)
        except Hub.DoesNotExist:
            return queryset.none()

        return queryset.filter(hubs__in=[hub])
