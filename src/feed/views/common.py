"""
Common functionality shared between feed ViewSets.
"""

from rest_framework.pagination import PageNumberPagination

# Cache timeout (30 minutes)
DEFAULT_CACHE_TIMEOUT = 60 * 30


class FeedPagination(PageNumberPagination):
    """
    Pagination class for feed endpoints.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
