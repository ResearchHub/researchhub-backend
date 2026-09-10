from rest_framework.throttling import UserRateThrottle


class FeedRecommendationRefreshThrottle(UserRateThrottle):
    scope = "force_refresh"
    rate = "5/min"

    def allow_request(self, request, view):
        # Only throttle if the force refresh header is present and set to "true"
        force_refresh = request.META.get("HTTP_RH_FORCE_REFRESH", "").lower() == "true"
        if not force_refresh:
            return True
        return super().allow_request(request, view)
