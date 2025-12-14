"""
Hot Score Implementation for Feed Entry Ranking

Calculates hot scores for feed entries using a declarative algorithm, similar
to Hacker News. The algorithm prioritizes content based on:
1. Bounties (especially new or expiring within 48h)
2. Tips/Boosts (financial support)
3. Peer reviews (expert feedback)
4. Comments (discussion activity)
5. Recency (time-based signal that never reaches zero)
6. Upvotes (community engagement)

Hot Score Formula:
    hot_score = (engagement_score / (age_in_hours + base_hours)^gravity) * 100

Where engagement_score is a weighted sum of logarithmic-scaled signals,
including a recency signal that ensures new content always surfaces.

Time Decay Philosophy:
- Uses gentle decay (gravity=0.8, base_hours=24) so documents from the same
  day are roughly equal, with engagement as the differentiator
- Exceptional content from yesterday CAN beat mediocre content from today
- ~37% score drop per day means 1.6x engagement overcomes 24h age difference

Recency Signal (Cold Start Solution):
- Recency is treated as a signal: recency_value = 24 / (age_hours + 24)
- Yields ~21 points at 0h, ~12 at 24h, ~7 at 72h, ~4 at 1 week
- Never reaches zero, ensuring all content has some base score

Temporal urgency handling:
- Expiring content urgency: Surfaces grants/preregistrations with approaching
  deadlines

Note: Scores are scaled by 100 and converted to integers to preserve precision
while allowing meaningful differentiation between items during sorting.
"""

import logging
import math

from django.contrib.contenttypes.models import ContentType

# Re-export from deprecated module for backward compatibility with tests
from feed.hot_score_DEPRECATED import CONTENT_TYPE_WEIGHTS  # noqa: F401
from feed.hot_score_utils import (
    get_age_hours_from_content,
    get_bounties_from_content,
    get_comment_count_from_metrics,
    get_fundraise_amount_from_content,
    get_peer_review_count_from_metrics,
    get_tips_from_content,
    get_upvotes_rolled_up,
    get_x_engagement_from_metrics,
)
from paper.related_models.paper_model import Paper
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from utils import sentry

logger = logging.getLogger(__name__)

# ContentType cache to avoid repeated database lookups
_CONTENT_TYPE_CACHE = {}


def get_content_type_for_model(model):
    """
    Get ContentType for a model with caching.

    Avoids repeated database lookups when calculating hot scores
    for multiple feed entries.

    Args:
        model: Django model class

    Returns:
        ContentType instance
    """
    cache_key = f"{model._meta.app_label}.{model._meta.model_name}"
    if cache_key not in _CONTENT_TYPE_CACHE:
        _CONTENT_TYPE_CACHE[cache_key] = ContentType.objects.get_for_model(model)
    return _CONTENT_TYPE_CACHE[cache_key]


# Hot Score Configuration
HOT_SCORE_CONFIG = {
    # Higher weight = more influence on final score
    # Weights sum to 100 for easier reasoning about relative importance
    "signals": {
        "x_engagement": {
            "weight": 25.0,
            "log_base": math.e,
        },
        "peer_review": {
            "weight": 20.0,
            "log_base": math.e,
        },
        "bounty": {
            "weight": 20.0,
            "log_base": math.e,
            "urgency_multiplier": 1.5,  # Boost for new/expiring
            "urgency_hours": 48,
        },
        "comment": {
            "weight": 15.0,
            "log_base": math.e,
        },
        "upvote": {
            "weight": 10.0,
            "log_base": math.e,
        },
        "tip": {
            "weight": 5.0,
            "log_base": math.e,
        },
        # Recency ensures new papers with no engagement don't get a zero score
        "recency": {
            "weight": 5.0,
            "log_base": math.e,
        },
    },
    # Time decay parameters control content prominence over time
    # Gentle decay ensures documents from same day compete on engagement
    "time_decay": {
        "gravity": 0.8,  # Gentler decay (was 1.5)
        "base_hours": 24,
    },
    # Temporal urgency configuration for content with approaching deadlines
    "temporal_urgency": {
        "expiring_content_urgency": {
            "grant_urgency_days": 7,  # Grant deadline urgency window
            "preregistration_urgency_days": 7,  # Preregistration deadline urgency
        },
    },
    # Configurable thresholds
    "thresholds": {
        "peer_review_min_score": 3,  # Min item.score for peer review to inherit parent
    },
}


# ============================================================================
# Signal Aggregation Helper Functions
# ============================================================================


def get_total_bounty_amount(feed_entry):
    """
    Sum all open bounties from FeedEntry content JSON.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        tuple: (total_amount: float, has_urgent_bounty: bool)
    """
    urgency_hours = HOT_SCORE_CONFIG["signals"]["bounty"]["urgency_hours"]
    return get_bounties_from_content(feed_entry.content, feed_entry, urgency_hours)


def get_total_tip_amount(feed_entry):
    """
    Sum all tips/boosts from FeedEntry content JSON and optionally comments.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        float: Total tip amount
    """
    return get_tips_from_content(feed_entry.content, feed_entry)


def get_total_upvotes(feed_entry):
    """
    Calculate total upvotes: document upvotes + rolled-up comment upvotes.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        int: Total upvote count
    """
    return get_upvotes_rolled_up(feed_entry.metrics, feed_entry)


def get_peer_review_count(feed_entry):
    """
    Count peer reviews from FeedEntry metrics JSON.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        int: Number of peer reviews
    """
    return get_peer_review_count_from_metrics(feed_entry.metrics)


def get_comment_count(feed_entry):
    """
    Count regular comments (excluding peer reviews) from FeedEntry metrics JSON.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        int: Number of comments
    """
    return get_comment_count_from_metrics(feed_entry.metrics)


def get_age_hours(feed_entry):
    """
    Calculate age in hours from FeedEntry content JSON, with urgency adjustments.

    For grants/preregistrations with approaching deadlines: Uses end_date for urgency

    Args:
        feed_entry: FeedEntry instance

    Returns:
        float: Age in hours
    """
    urgency_config = HOT_SCORE_CONFIG["temporal_urgency"]["expiring_content_urgency"]
    grant_urgency_days = urgency_config["grant_urgency_days"]
    prereg_urgency_days = urgency_config["preregistration_urgency_days"]

    return get_age_hours_from_content(
        feed_entry.content, feed_entry, grant_urgency_days, prereg_urgency_days
    )


def get_fundraise_amount(feed_entry):
    """
    Get fundraise amount for PREREGISTRATION posts from FeedEntry content JSON.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        float: Amount raised, or 0 if not applicable
    """
    return get_fundraise_amount_from_content(feed_entry.content)


def get_x_engagement(feed_entry) -> float:
    """Get X engagement score from FeedEntry metrics JSON."""
    return get_x_engagement_from_metrics(feed_entry.metrics)


# ============================================================================
# Main Hot Score Calculation Functions
# ============================================================================


def calculate_hot_score_for_item(feed_entry):
    """
    Calculate hot score for a feed entry item.

    Routes to appropriate calculation based on content type.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        int: Calculated hot score
    """
    item = feed_entry.item
    item_content_type = ContentType.objects.get_for_model(item)

    comment_ct = get_content_type_for_model(RhCommentModel)
    post_ct = get_content_type_for_model(ResearchhubPost)
    paper_ct = get_content_type_for_model(Paper)

    if item_content_type == comment_ct and (
        item.comment_type == COMMUNITY_REVIEW or item.comment_type == PEER_REVIEW
    ):
        # Only calculate hot score for peer review comments
        return calculate_hot_score_for_peer_review(feed_entry)
    elif item_content_type == post_ct or item_content_type == paper_ct:
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
            get_content_type_for_model(ResearchhubPost),
            get_content_type_for_model(Paper),
        ],
    )

    parent_score = 0
    min_score = HOT_SCORE_CONFIG["thresholds"]["peer_review_min_score"]
    if feed_entries.count() > 0 and item.score >= min_score:
        # Only use the hot score if the parent item meets minimum score threshold
        # Use hot_score_v2 (the new algorithm)
        parent_score = feed_entries.first().hot_score_v2 or 0

    peer_review_score = calculate_hot_score(
        feed_entry,
        get_content_type_for_model(RhCommentModel),
    )

    # Add the peer review's own score to ensure it ranks higher than the original paper
    # Note: Both parent_score and peer_review_score are already scaled by 100
    final_score = int(parent_score + peer_review_score)

    return max(0, final_score)


def calculate_hot_score(feed_entry, content_type_name, return_components=False):
    """
    Calculate hot score using HN-style algorithm with prioritized signals.

    Formula:
        hot_score = (engagement_score / (age_hours + base_hours)^gravity) * 100

    Where engagement_score is weighted sum of:
        1. Bounties (with urgency multiplier)
        2. Tips/Boosts
        3. Peer reviews
        4. Comments
        5. Recency (time-based signal that never reaches zero)
        6. Upvotes

    The recency signal ensures new content always has a base score, solving
    the cold start problem. Formula: recency_value = 24 / (age_hours + 24)
    This yields ~21 points at 0h, ~12 at 24h, ~7 at 72h, and never reaches 0.

    Time Decay Philosophy:
    Uses gentle decay (gravity=0.8, base_hours=24) optimized for scientific content
    that publishes infrequently. Documents from the same day compete primarily on
    engagement, but exceptional content from yesterday CAN beat today's mediocre
    content (~1.6x engagement overcomes 24h age difference).

    The final score is scaled by 100 and converted to an integer to preserve
    precision while allowing meaningful differentiation between items.

    Args:
        feed_entry: The feed entry object
        content_type_name: ContentType instance
        return_components: If True, return dict with score and all components

    Returns:
        int: Calculated hot score (if return_components=False)
        dict: Full calculation data (if return_components=True)
    """
    try:
        # ====================================================================
        # 1. Gather all signals from FeedEntry JSON fields
        # ====================================================================

        # Bounties (with urgency detection)
        bounty_amount, has_urgent_bounty = get_total_bounty_amount(feed_entry)

        # Tips/Boosts
        tip_amount = get_total_tip_amount(feed_entry)

        # Peer reviews
        peer_review_count = get_peer_review_count(feed_entry)

        # Upvotes (document + comments rolled up)
        upvote_count = get_total_upvotes(feed_entry)

        # Comments (excluding peer reviews)
        comment_count = get_comment_count(feed_entry)

        # Fundraise amount (for PREREGISTRATION)
        fundraise_amount = get_fundraise_amount(feed_entry)
        if fundraise_amount > 0:
            # Treat fundraise amount like tips
            tip_amount += fundraise_amount

        # Age in hours
        age_hours = get_age_hours(feed_entry)

        # X/Twitter engagement
        x_engagement = get_x_engagement(feed_entry)

        # ====================================================================
        # 2. Calculate engagement score using logarithmic scaling
        # ====================================================================

        config = HOT_SCORE_CONFIG["signals"]

        # Each signal is log-scaled to prevent large values from dominating
        # Bounty gets urgency multiplier if new or expiring soon
        bounty_multiplier = (
            config["bounty"]["urgency_multiplier"] if has_urgent_bounty else 1.0
        )
        bounty_component = (
            math.log(bounty_amount + 1, config["bounty"]["log_base"])
            * config["bounty"]["weight"]
            * bounty_multiplier
        )

        tip_component = (
            math.log(tip_amount + 1, config["tip"]["log_base"])
            * config["tip"]["weight"]
        )

        peer_review_component = (
            math.log(peer_review_count + 1, config["peer_review"]["log_base"])
            * config["peer_review"]["weight"]
        )

        comment_component = (
            math.log(comment_count + 1, config["comment"]["log_base"])
            * config["comment"]["weight"]
        )

        # Recency: 24/(age+24) yields 1.0 at 0h, 0.5 at 24h, never reaches 0
        recency_value = 24.0 / (age_hours + 24.0)
        recency_component = (
            math.log(recency_value + 1, config["recency"]["log_base"])
            * config["recency"]["weight"]
        )

        upvote_component = (
            math.log(upvote_count + 1, config["upvote"]["log_base"])
            * config["upvote"]["weight"]
        )

        x_engagement_component = (
            math.log(x_engagement + 1, config["x_engagement"]["log_base"])
            * config["x_engagement"]["weight"]
        )

        # Sum all components
        engagement_score = (
            bounty_component
            + tip_component
            + peer_review_component
            + comment_component
            + recency_component
            + upvote_component
            + x_engagement_component
        )

        # ====================================================================
        # 3. Apply time decay
        # ====================================================================

        decay_config = HOT_SCORE_CONFIG["time_decay"]
        gravity = decay_config["gravity"]
        base_hours = decay_config["base_hours"]

        # Denominator grows with age, drastically reducing score over time
        # base_hours prevents division by zero and softens decay for very new content
        denominator = math.pow(age_hours + base_hours, gravity)

        # Final score
        if denominator > 0:
            hot_score = engagement_score / denominator
        else:
            hot_score = engagement_score

        # Scale by 100 to preserve precision, then convert to integer
        # This allows for better differentiation between items
        # Example: 0.0051 → 0, 1.5 → 150, 10.25 → 1025
        scaled_score = hot_score * 100
        final_score = max(0, int(scaled_score))

        # Return components if requested (for breakdown generation)
        if return_components:
            return {
                "final_score": final_score,
                "raw_signals": {
                    "bounty": bounty_amount,
                    "tip": tip_amount,
                    "peer_review": peer_review_count,
                    "comment": comment_count,
                    "recency": recency_value,
                    "upvote": upvote_count,
                    "x_engagement": x_engagement,
                },
                "components": {
                    "bounty": bounty_component,
                    "tip": tip_component,
                    "peer_review": peer_review_component,
                    "comment": comment_component,
                    "recency": recency_component,
                    "upvote": upvote_component,
                    "x_engagement": x_engagement_component,
                },
                "bounty_urgent": has_urgent_bounty,
                "bounty_multiplier": bounty_multiplier,
                "time_factors": {
                    "age_hours": age_hours,
                    "base_hours": base_hours,
                    "gravity": gravity,
                },
                "engagement_score": engagement_score,
                "time_denominator": denominator,
                "raw_score": hot_score,
            }

        return final_score

    except Exception as e:
        logger.error(f"Error calculating hot score for feed_entry {feed_entry.id}: {e}")
        sentry.log_error(e)
        if return_components:
            return None
        return 0
