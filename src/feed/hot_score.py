"""
Hot Score Implementation for Feed Entry Ranking

Calculates content-type specific hot scores for ranking feed entries.
"""

import logging
import math
from datetime import datetime, timezone

from django.contrib.contenttypes.models import ContentType

from paper.related_models.paper_model import Paper
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from utils import sentry

logger = logging.getLogger(__name__)

# Content Type Weights
# These weights will be used to adjust the importance of different signals
# based on content type
#    - vote_weight: Base vote weight (upvotes - downvotes)
#    - reply_weight: Weight for discussions/comments
#    - bounty_weight: Weight for bounties
#    - time_decay_factor: How quickly score decays with time
#    - half_life_days: Decay half-life in days
CONTENT_TYPE_WEIGHTS = {
    "paper": {
        "vote_weight": 1.0,
        "reply_weight": 1.0,
        "bounty_weight": 3.0,
        "time_decay_factor": 0.90,
        "half_life_days": 3,
    },
    "researchhubpost": {
        "vote_weight": 1.0,
        "reply_weight": 1.0,
        "bounty_weight": 3.0,
        "time_decay_factor": 0.90,
        "half_life_days": 3,
    },
    "rhcommentmodel": {
        "vote_weight": 1.0,
        "reply_weight": 1.0,
        "bounty_weight": 3.0,
        "time_decay_factor": 0.90,
        "half_life_days": 3,
    },
}


def calculate_hot_score_for_item(item):
    """
    Calculate hot score for an item
    """
    item_content_type = ContentType.objects.get_for_model(item)
    if item_content_type == ContentType.objects.get_for_model(RhCommentModel) and (
        item.comment_type == COMMUNITY_REVIEW or item.comment_type == PEER_REVIEW
    ):
        # Only calculate hot score for peer review comments
        return calculate_hot_score_for_peer_review(item)
    else:
        return calculate_hot_score(item, item_content_type)


def calculate_hot_score_for_peer_review(comment):
    """
    Calculate hot score for a peer review differs from the hot score for a paper
    and posts because we get the score of the paper or post and then add peer review.
    This ensures that the peer review shows up in the feed instead of the paper or post
    since we distinct on unified_document_id.
    """
    # Get the base score from the associated paper or post
    unified_document = comment.unified_document
    if not unified_document:
        return 0

    feed_entries = unified_document.feed_entries.filter(
        content_type__in=[
            ContentType.objects.get_for_model(ResearchhubPost),
            ContentType.objects.get_for_model(Paper),
        ],
    )

    parent_score = 0
    if feed_entries.count() == 1:
        parent_score = feed_entries.first().hot_score or 0
    else:
        logger.info(
            f"Expected 1 feed entry for unified document {unified_document.id}, got {feed_entries.count()}"
        )
        sentry.log_info(
            f"Expected 1 feed entry for unified document {unified_document.id}, got {feed_entries.count()}"
        )

    peer_review_score = calculate_hot_score(
        comment,
        ContentType.objects.get_for_model(RhCommentModel),
    )

    # Add the peer review's own score to ensure it ranks higher than the original paper
    final_score = int(parent_score + (peer_review_score))
    return max(1, final_score)


def calculate_hot_score(item, content_type_name):
    """
    Calculate hot score for an item based on its content type.

    Args:
        item: The item object (paper, post, comment, etc.)
        content_type_name: String name of the content type

    Returns:
        Calculated hot score as an integer
    """
    # Default to paper weights if content type not found
    weights = CONTENT_TYPE_WEIGHTS.get(content_type_name, CONTENT_TYPE_WEIGHTS["paper"])

    # Get common attributes with defaults
    vote_score = getattr(item, "score", 0) or 0
    reply_county = 0
    if hasattr(item, "get_discussion_count"):
        reply_county = item.get_discussion_count()
    if hasattr(item, "children_count"):
        reply_county = getattr(item, "children_count", 0) or 0

    created_date = getattr(item, "created_date", datetime.now(timezone.utc))

    bounty_amount = 0
    if hasattr(item, "bounties"):
        try:
            bounty_amount = sum(bounty.amount for bounty in item.bounties.all())
        except Exception:
            pass

    vote_component = vote_score * weights.get("vote_weight", 1.0)
    discussion_component = (
        math.log(reply_county + 1) * weights.get("reply_weight", 0.5) * 10
    )
    bounty_component = math.sqrt(bounty_amount) * weights.get("bounty_weight", 1.5)

    score = vote_component + discussion_component + bounty_component

    half_life_seconds = weights.get("half_life_days", 7) * 24 * 60 * 60
    age_seconds = (datetime.now(timezone.utc) - created_date).total_seconds()
    # This formula calculates a decay factor between 0 and 1, where:
    # - Fresh content (age = 0) gets a decay factor of 1.0 (no decay)
    # - Content at exactly half-life age gets a factor of 0.5 (50% reduction)
    # - Older content gets progressively smaller factors approaching zero
    time_decay = math.pow(2, -age_seconds / half_life_seconds)

    final_score = int(score * time_decay)

    return max(1, final_score)
