"""
Common functionality shared between feed ViewSets.
"""

from django.contrib.contenttypes.models import ContentType
from requests import Request
from rest_framework.pagination import PageNumberPagination

from discussion.reaction_serializers import VoteSerializer as GrmVoteSerializer
from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.views.researchhub_unified_document_views import get_user_votes

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


def add_user_votes_to_response(user, response_data):
    """
    Add user votes to feed items in the response data.

    Args:
        user: The authenticated user
        response_data: The response data containing feed items
    """
    # Get content types once to avoid repeated database queries
    paper_content_type = ContentType.objects.get_for_model(Paper)
    post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
    comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
    bounty_content_type = ContentType.objects.get_for_model(Bounty)

    # Get uppercase model names from ContentType objects
    paper_type_str = paper_content_type.model.upper()
    post_type_str = post_content_type.model.upper()
    comment_type_str = comment_content_type.model.upper()
    bounty_type_str = bounty_content_type.model.upper()

    # Map content type strings to their ContentType objects
    content_type_map = {
        paper_type_str: paper_content_type,
        post_type_str: post_content_type,
        comment_type_str: comment_content_type,
        bounty_type_str: bounty_content_type,
    }

    paper_ids = []
    post_ids = []
    comment_ids = []

    # Collect IDs for each content type
    for item in response_data["results"]:
        content_type_str = item.get("content_type")
        if content_type_str == paper_type_str:
            paper_ids.append(int(item["content_object"]["id"]))
        elif content_type_str == post_type_str:
            post_ids.append(int(item["content_object"]["id"]))
        elif content_type_str == comment_type_str:
            comment_ids.append(int(item["content_object"]["id"]))
        elif content_type_str == bounty_type_str:
            # For bounties, we need to get the comment ID if it exists
            if item["content_object"].get("comment") and item["content_object"][
                "comment"
            ].get("id"):
                comment_ids.append(int(item["content_object"]["comment"]["id"]))

    # Process paper votes
    if paper_ids:
        paper_votes = get_user_votes(
            user,
            paper_ids,
            content_type_map[paper_type_str],
        )

        paper_votes_map = {}
        for vote in paper_votes:
            paper_votes_map[int(vote.object_id)] = GrmVoteSerializer(vote).data

        for item in response_data["results"]:
            if item.get("content_type") == paper_type_str:
                paper_id = int(item["content_object"]["id"])
                if paper_id in paper_votes_map:
                    item["user_vote"] = paper_votes_map[paper_id]

    # Process post votes
    if post_ids:
        post_votes = get_user_votes(
            user,
            post_ids,
            content_type_map[post_type_str],
        )

        post_votes_map = {}
        for vote in post_votes:
            post_votes_map[int(vote.object_id)] = GrmVoteSerializer(vote).data

        for item in response_data["results"]:
            if item.get("content_type") == post_type_str:
                post_id = int(item["content_object"]["id"])
                if post_id in post_votes_map:
                    item["user_vote"] = post_votes_map[post_id]

    # Process comment votes
    if comment_ids:
        comment_votes = get_user_votes(
            user,
            comment_ids,
            content_type_map[comment_type_str],
        )

        comment_votes_map = {}
        for vote in comment_votes:
            comment_votes_map[int(vote.object_id)] = GrmVoteSerializer(vote).data

        for item in response_data["results"]:
            if item.get("content_type") == comment_type_str:
                comment_id = int(item["content_object"]["id"])
                if comment_id in comment_votes_map:
                    item["user_vote"] = comment_votes_map[comment_id]
            # Handle bounties with comments
            elif item.get("content_type") == bounty_type_str and item[
                "content_object"
            ].get("comment"):
                comment_id = int(item["content_object"]["comment"]["id"])
                if comment_id in comment_votes_map:
                    item["user_vote"] = comment_votes_map[comment_id]
