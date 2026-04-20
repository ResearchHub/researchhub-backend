from django.core.cache import cache

from feed.views.common import FeedPagination
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

GRANT_FEED_ORDERINGS = [
    "latest",
    "newest",
    "upvotes",
    "most_applicants",
    "amount_raised",
]
GRANT_FEED_STATUSES = ["", "OPEN", "CLOSED", "COMPLETED", "PENDING"]
GRANT_FEED_MAX_CACHED_PAGE = 3


class GrantCacheMixin:
    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        status = request.query_params.get("status", "")
        created_by = request.query_params.get("created_by", "")
        return f"{base_key}:{status}:{created_by}"

    @staticmethod
    def invalidate_grant_feed_cache():
        page_size = FeedPagination.page_size
        creator_ids = (
            ResearchhubPost.objects.filter(document_type=GRANT)
            .values_list("created_by_id", flat=True)
            .distinct()
        )
        created_by_values = [""] + [str(cid) for cid in creator_ids if cid is not None]

        for ordering in GRANT_FEED_ORDERINGS:
            sort_part = f"-{ordering}" if ordering != "latest" else ""
            for status in GRANT_FEED_STATUSES:
                for created_by in created_by_values:
                    for page in range(1, GRANT_FEED_MAX_CACHED_PAGE + 1):
                        cache_key = (
                            f"grants_feed:popular:all:all:none:"
                            f"{page}-{page_size}{sort_part}:{status}:{created_by}"
                        )
                        cache.delete(cache_key)
