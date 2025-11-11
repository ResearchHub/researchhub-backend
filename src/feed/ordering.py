from rest_framework.filters import BaseFilterBackend

from feed.feed_config import FEED_CONFIG


class FeedOrderingBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        # Skip ordering if queryset is already diversified to preserve the diversification order
        if getattr(view, "_is_diversified", False):
            return queryset

        feed_view = request.query_params.get("feed_view", "popular")
        ordering_param = request.query_params.get("ordering")

        feed_config = FEED_CONFIG.get(feed_view, {})
        allowed_sorts = feed_config.get("allowed_sorts", [])

        if ordering_param and ordering_param in allowed_sorts:
            ordering_field = self._map_ordering_to_field(ordering_param)
            return queryset.order_by(ordering_field)

        if allowed_sorts:
            default_ordering = self._map_ordering_to_field(allowed_sorts[0])
            return queryset.order_by(default_ordering)

        return queryset.order_by("-action_date")

    def _map_ordering_to_field(self, ordering_value):
        ordering_map = {
            "hot_score_v2": "-hot_score_v2",
            "hot_score": "-hot_score",
            "latest": "-action_date",
        }
        return ordering_map.get(ordering_value, "-action_date")
