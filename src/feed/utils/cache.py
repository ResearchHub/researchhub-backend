"""
Cache invalidation utilities for feed-related caches.
"""

from django.core.cache import cache


def invalidate_feed_cache_for_user(user_id):
    """
    Invalidate all feed caches for a specific user.

    This should be called when a user's feed preferences change, such as:
    - Following/unfollowing hubs
    - Following/unfollowing users
    - Any other action that affects what content appears in their feed

    Args:
        user_id: The ID of the user whose caches should be invalidated
    """
    # Cache key pattern: {feed_type}_feed:{feed_view}:{hub_part}:{source_part}:{user_part}:{pagination_part}{status_part}{sort_part}
    # For following feed, user_part is the user_id
    # We need to invalidate all possible combinations for this user

    # Django's cache doesn't support wildcard deletion out of the box
    # For now, we'll delete specific known cache keys for common pagination scenarios
    # Pages 1-4, page sizes 20 and 40
    feed_views = ["following"]
    hub_parts = ["all"]
    source_parts = ["all", "researchhub"]
    pages = ["1", "2", "3", "4"]
    page_sizes = ["20"]

    # Main feed caches (the primary personalized feed)
    # This is the only feed that has personalized "following" view
    for feed_view in feed_views:
        for hub_part in hub_parts:
            for source_part in source_parts:
                for page in pages:
                    for page_size in page_sizes:
                        cache_key = f"feed:{feed_view}:{hub_part}:{source_part}:{user_id}:{page}-{page_size}"
                        cache.delete(cache_key)

                        # Also with hot_score sort
                        cache_key_hot = f"{cache_key}-hot_score"
                        cache.delete(cache_key_hot)
