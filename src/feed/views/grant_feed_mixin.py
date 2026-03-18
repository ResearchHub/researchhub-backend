from django.core.cache import cache

from feed.views.common import FeedPagination

GRANT_FEED_ORDERINGS = ["latest", "newest", "upvotes", "most_applicants", "amount_raised"]
GRANT_FEED_STATUSES = ["", "OPEN", "CLOSED", "COMPLETED", "PENDING"]
GRANT_FEED_MAX_CACHED_PAGE = 3


class GrantFeedMixin:
    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        status = request.query_params.get("status", "")
        return f"{base_key}:{status}"

    @staticmethod
    def invalidate_grant_feed_cache():
        page_size = FeedPagination.page_size
        for ordering in GRANT_FEED_ORDERINGS:
            sort_part = f"-{ordering}" if ordering != "latest" else ""
            for status in GRANT_FEED_STATUSES:
                for page in range(1, GRANT_FEED_MAX_CACHED_PAGE + 1):
                    cache_key = (
                        f"grants_feed:popular:all:all:none:"
                        f"{page}-{page_size}{sort_part}:{status}"
                    )
                    cache.delete(cache_key)
