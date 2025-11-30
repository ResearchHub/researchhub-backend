from rest_framework.filters import BaseFilterBackend

from feed.feed_config import FEED_CONFIG


class FeedOrderingBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        feed_view = request.query_params.get("feed_view", "popular")
        # Personalized feed is ordered by the Personalize service
        if feed_view == "personalized":
            return queryset

        # If _feed_source is "aws-*", filtering already handled sorting in-memory
        feed_source = getattr(view, "_feed_source", None)

        if feed_view == "popular" and feed_source == "aws-trending":
            return queryset

        # If rh-popular (fallback), use hot_score_v2 ordering
        if feed_view == "popular" and feed_source == "rh-popular":
            return queryset.order_by("-hot_score_v2")

        ordering_param = request.query_params.get("ordering")

        feed_config = FEED_CONFIG.get(feed_view, {})
        allowed_sorts = feed_config.get("allowed_sorts", [])

        if ordering_param and ordering_param in allowed_sorts:
            ordering_field = self._map_ordering_to_field(ordering_param)
            if ordering_field:
                return queryset.order_by(ordering_field)

        if allowed_sorts:
            default_ordering = self._map_ordering_to_field(allowed_sorts[0])
            if default_ordering:
                return queryset.order_by(default_ordering)

        return queryset.order_by("-action_date")

    def _map_ordering_to_field(self, ordering_value):
        ordering_map = {
            "hot_score_v2": "-hot_score_v2",
            "hot_score": "-hot_score",
            "latest": "-action_date",
            # aws_trending is handled by filtering backend, not DB ordering
            "aws_trending": None,
        }
        return ordering_map.get(ordering_value, "-action_date")
