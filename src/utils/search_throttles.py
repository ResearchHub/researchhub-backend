"""
Search-specific throttling classes for bot and DDoS mitigation.

Multi-tier throttling approach:
- Burst protection: Prevents rapid-fire attacks
- Sustained limit: Prevents sustained abuse
- Daily limit: Prevents systematic scraping
"""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class SearchAnonBurstThrottle(AnonRateThrottle):
    """
    Short-term burst protection for anonymous search queries.
    Prevents rapid-fire requests (e.g., 10 requests in 1 second).
    """

    scope = "search_anon_burst"
    rate = "5/second"


class SearchAnonRateThrottle(AnonRateThrottle):
    """
    Sustained rate limit for anonymous search queries.
    More restrictive than default DRF throttling (20/min vs 50/min).
    """

    scope = "search_anon"
    rate = "20/minute"


class SearchAnonDailyThrottle(AnonRateThrottle):
    """
    Long-term protection against systematic scraping.
    Cumulative daily limit for anonymous users.
    """

    scope = "search_anon_daily"
    rate = "500/day"


class SearchUserRateThrottle(UserRateThrottle):
    """
    Rate limit for authenticated user searches.
    Higher limits for logged-in users (100/min).
    """

    scope = "search_user"
    rate = "100/minute"

