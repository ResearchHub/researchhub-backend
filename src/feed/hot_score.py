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
#    - half_life_days: Decay half-life in days
CONTENT_TYPE_WEIGHTS = {
    "paper": {
        "vote_weight": 100.0,
        "reply_weight": 50.0,
        "bounty_weight": 400.0,
        "half_life_days": 5,
    },
    "researchhubpost": {
        "vote_weight": 100.0,
        "reply_weight": 50.0,
        "bounty_weight": 400.0,
        "half_life_days": 5,
    },
    "rhcommentmodel": {
        "vote_weight": 100.0,
        "reply_weight": 50.0,
        "bounty_weight": 400.0,
        "half_life_days": 5,
    },
}


def calculate_hot_score_for_item(feed_entry):
    """
    Calculate hot score for an item
    """
    item = feed_entry.item
    item_content_type = ContentType.objects.get_for_model(item)

    if item_content_type == ContentType.objects.get_for_model(RhCommentModel) and (
        item.comment_type == COMMUNITY_REVIEW or item.comment_type == PEER_REVIEW
    ):
        # Only calculate hot score for peer review comments
        return calculate_hot_score_for_peer_review(feed_entry)
    elif item_content_type == ContentType.objects.get_for_model(
        ResearchhubPost
    ) or item_content_type == ContentType.objects.get_for_model(Paper):
        return calculate_hot_score(feed_entry, item_content_type)
    else:
        return 0


def calculate_hot_score_for_peer_review(feed_entry):
    """
    Calculate hot score for a peer review differs from the hot score for a paper
    and posts because we get the score of the paper or post and then add peer review.
    This ensures that the peer review shows up in the feed instead of the paper or post
    since we distinct on unified_document_id.
    """
    # Get the base score from the associated paper or post
    item = feed_entry.item
    unified_document = feed_entry.unified_document
    if not unified_document:
        return 0

    feed_entries = unified_document.feed_entries.filter(
        content_type__in=[
            ContentType.objects.get_for_model(ResearchhubPost),
            ContentType.objects.get_for_model(Paper),
        ],
    )

    parent_score = 0
    if feed_entries.count() > 0 and item.score >= 3:
        # Only use the hot score if the parent item has a score of 3 or higher
        parent_score = feed_entries.first().hot_score or 0

    peer_review_score = calculate_hot_score(
        feed_entry,
        ContentType.objects.get_for_model(RhCommentModel),
    )

    # Add the peer review's own score to ensure it ranks higher than the original paper
    # Subtract 1 to ensure some interaction on our site
    final_score = int(parent_score + peer_review_score - 1)

    return max(1, final_score)


def calculate_hot_score(feed_entry, content_type_name):
    """
    Calculate hot score for a feed entry based on its content type.

    Args:
        feed_entry: The feed entry object
        content_type_name: String name of the content type

    Returns:
        Calculated hot score as an integer
    """
    # Default to paper weights if content type not found
    item = feed_entry.item
    unified_document = feed_entry.unified_document
    weights = CONTENT_TYPE_WEIGHTS.get(content_type_name.model)
    if not weights:
        logger.info(f"No weights found for content type {content_type_name.model}")
        sentry.log_info(f"No weights found for content type {content_type_name.model}")
        return 0

    # Get common attributes with defaults
    vote_score = getattr(item, "score", 0) or 0
    reply_county = 0
    if hasattr(item, "discussion_count"):
        reply_county = getattr(item, "discussion_count", 0) or 0
    if hasattr(item, "children_count"):
        reply_county = getattr(item, "children_count", 0) or 0

    created_date = getattr(item, "created_date", datetime.now(timezone.utc))

    bounty_amount = 0
    if hasattr(item, "bounties"):
        bounties = item.bounties.all()

    elif hasattr(unified_document, "bounties"):
        bounties = unified_document.bounties.all()
    else:
        bounties = []

    bounty_amount = sum(bounty.amount for bounty in bounties)

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
