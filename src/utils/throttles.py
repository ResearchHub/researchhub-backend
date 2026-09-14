import logging
from ipaddress import ip_address

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

logger = logging.getLogger(__name__)


class CloudflareClientIPMixin:
    """
    Mixing class for throttle implementations that overrides the `get_ident` method to
    use the Cloudflare connecting IP address (`HTTP_CF_CONNECTING_IP`).
    This is safer than using `X-Forwarded-For` since it cannot be spoofed by the client.
    Falls back to the standard REMOTE_ADDR if the Cloudflare header is not present
    or invalid.
    """

    def get_ident(self, request):
        value = request.META.get("HTTP_CF_CONNECTING_IP")

        if value:
            try:
                return str(ip_address(value))
            except ValueError:
                logger.warning("Invalid IP address in HTTP_CF_CONNECTING_IP: %s", value)

        # Fall back to the standard REMOTE_ADDR if the Cloudflare header is not present
        # or invalid since X-Forwarded-For can be spoofed by the client.
        return request.META.get("REMOTE_ADDR")


class CloudflareAnonRateThrottle(CloudflareClientIPMixin, AnonRateThrottle):
    """
    Throttle class for anonymous users that uses the Cloudflare connecting IP address
    for identification.
    """


class FeedRecommendationRefreshThrottle(CloudflareClientIPMixin, UserRateThrottle):
    scope = "force_refresh"
    rate = "5/min"

    def allow_request(self, request, view):
        # Only throttle if the force refresh header is present and set to "true"
        force_refresh = request.META.get("HTTP_RH_FORCE_REFRESH", "").lower() == "true"
        if not force_refresh:
            return True
        return super().allow_request(request, view)
