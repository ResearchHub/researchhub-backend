from rest_framework.filters import BaseFilterBackend

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
        if not request.user.is_authenticated:
            return queryset

        try:
            personalize_client = getattr(view, "personalize_client", None)
            if not personalize_client:
                return queryset

            page_size = view.paginator.page_size if hasattr(view, "paginator") else 30
            recommended_ids = personalize_client.get_recommendations_for_user(
                user_id=str(request.user.id),
                num_results=page_size * 3,
            )

            if recommended_ids:
                return queryset.filter(id__in=recommended_ids)

            return queryset
        except Exception:
            return queryset

    def _filter_by_hub(self, hub_slug, queryset):
        try:
            hub = Hub.objects.get(slug=hub_slug)
        except Hub.DoesNotExist:
            return queryset.none()

        return queryset.filter(hubs__in=[hub])
