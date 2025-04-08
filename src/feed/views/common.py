"""
Common functionality shared between feed ViewSets.
"""

from requests import Request
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


def get_common_serializer_context():
    """
    Returns common serializer context used across feed-related viewsets.
    """
    context = {}
    context["pch_dfs_get_created_by"] = {
        "_include_fields": (
            "id",
            "author_profile",
            "first_name",
            "last_name",
        )
    }
    context["usr_dus_get_author_profile"] = {
        "_include_fields": (
            "id",
            "first_name",
            "last_name",
            "created_date",
            "updated_date",
            "profile_image",
            "is_verified",
        )
    }
    return context


def get_cache_key(request: Request, feed_type: str = "") -> str:
    feed_view = request.query_params.get("feed_view", "latest")
    hub_slug = request.query_params.get("hub_slug")
    user_id = request.user.id if request.user.is_authenticated else None
    fundraise_status = request.query_params.get("fundraise_status", None)

    page = request.query_params.get("page", "1")
    page_size = request.query_params.get(
        FeedPagination.page_size_query_param,
        str(FeedPagination.page_size),
    )

    hub_part = hub_slug or "all"
    user_part = (
        "none"
        if feed_view == "popular" or feed_view == "latest"
        else f"{user_id or 'anonymous'}"
    )
    pagination_part = f"{page}-{page_size}"
    status_part = f"-{fundraise_status}" if fundraise_status else ""
    feed_type_part = f"{feed_type}_" if feed_type else ""

    source = request.query_params.get("source")
    source_part = f"{source}" if source else "all"

    return f"{feed_type_part}feed:{feed_view}:{hub_part}:{source_part}:{user_part}:{pagination_part}{status_part}"
