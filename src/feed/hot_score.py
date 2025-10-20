"""
Hot Score Implementation for Feed Entry Ranking

Calculates hot scores for feed entries using a declarative algorithm, similar
to Hacker News. The algorithm prioritizes content based on:
1. Bounties (especially new or expiring within 24h)
2. Altmetric score (external engagement metrics)
3. Tips/Boosts (financial support)
4. Peer reviews (expert feedback)
5. Upvotes (community engagement)
6. Comments (discussion activity)
7. Recency (time decay with polynomial function)
8. Temporal urgency (boosts for new content and approaching deadlines)

Hot Score Formula:
    hot_score = ((engagement_score * freshness_multiplier) /
                 (age_in_hours + base_hours)^gravity) * 100

Where engagement_score is a weighted sum of logarithmic-scaled signals.

Temporal urgency handling:
- New content boost: 4.5x → 1.0x for ResearchHub posts over first 48 hours
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
    get_altmetric_from_metrics,
    get_bounties_from_content,
    get_comment_count_from_metrics,
    get_content_type_name,
    get_fundraise_amount_from_content,
    get_peer_review_count_from_metrics,
    get_tips_from_content,
    get_upvotes_rolled_up,
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

# Hot Score Configuration
HOT_SCORE_CONFIG = {
    # Higher weight = more influence on final score
    "signals": {
        "altmetric": {
            "weight": 100.0,  # external impact
            "log_base": math.e,  # Natural log for smooth scaling
        },
        "bounty": {
            "weight": 80.0,
            "log_base": math.e,
            "urgency_multiplier": 1.5,  # Boost for new/expiring
            "urgency_hours": 48,
        },
        "tip": {
            "weight": 60.0,
            "log_base": math.e,
        },
        "peer_review": {
            "weight": 50.0,
            "log_base": math.e,
        },
        "upvote": {
            "weight": 40.0,
            "log_base": math.e,
        },
        "comment": {
            "weight": 20.0,
            "log_base": math.e,
        },
    },
    # Time decay parameters control content prominence over time
    "time_decay": {
        "gravity": 1.8,  # higher = faster decay
        "base_hours": 20,  # Softens decay for very new content
    },
    # Temporal urgency configuration
    # Handles time-sensitive boosts for both new and expiring content
    "temporal_urgency": {
        # Boost new content before it accumulates engagement signals
        "new_content_boost": {
            "enabled": True,
            "cutoff_hours": 48,  # Boost decays to 1x at this point
            "initial_multipliers": {
                "researchhubpost": 4.5,  # 4.5x boost for new posts
                "paper": 1.0,  # No boost for papers (they have altmetric advantage)
            },
        },
        # Surface content with approaching deadlines
        "expiring_content_urgency": {
            "grant_urgency_days": 7,  # Grant deadline urgency window
            "preregistration_urgency_days": 7,  # Preregistration deadline urgency
        },
    },
}


# ============================================================================
# Signal Aggregation Helper Functions
# ============================================================================


def get_altmetric_score(feed_entry):
    """
    Extract altmetric score from FeedEntry metrics JSON.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        float: Altmetric score, or 0 if not available
    """
    return get_altmetric_from_metrics(feed_entry.metrics)


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


def get_freshness_multiplier(feed_entry, age_hours):
    """
    Calculate time-decaying freshness boost for new content.

    Provides a strong boost for brand new content that linearly decays
    to 1x (no boost) over the configured cutoff period.

    Formula:
        multiplier = 1 + (initial_boost - 1) * (1 - age_hours / cutoff_hours)
        clamped to [1.0, initial_boost]

    Args:
        feed_entry: FeedEntry instance
        age_hours: Age of the content in hours

    Returns:
        float: Freshness multiplier (e.g., 3.0 for brand new post, 1.0 after 48h)
    """
    config = HOT_SCORE_CONFIG["temporal_urgency"]["new_content_boost"]

    # Check if freshness boost is enabled
    if not config.get("enabled", False):
        return 1.0

    # Get the appropriate initial multiplier based on content type
    initial_multipliers = config.get("initial_multipliers", {})
    content_type = get_content_type_name(feed_entry)
    initial_boost = initial_multipliers.get(content_type, 1.0)

    # If no boost configured, return 1.0
    if initial_boost <= 1.0:
        return 1.0

    cutoff_hours = config.get("cutoff_hours", 48)

    # If age exceeds cutoff, no boost
    if age_hours >= cutoff_hours:
        return 1.0

    # Calculate linear decay from initial_boost to 1.0
    # Formula: 1 + (initial_boost - 1) * (1 - age_hours / cutoff_hours)
    decay_factor = 1.0 - (age_hours / cutoff_hours)
    multiplier = 1.0 + (initial_boost - 1.0) * decay_factor

    # Ensure multiplier is in valid range [1.0, initial_boost]
    return max(1.0, min(initial_boost, multiplier))


def get_fundraise_amount(feed_entry):
    """
    Get fundraise amount for PREREGISTRATION posts from FeedEntry content JSON.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        float: Amount raised, or 0 if not applicable
    """
    return get_fundraise_amount_from_content(feed_entry.content)


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
    # Note: Both parent_score and peer_review_score are already scaled by 100
    final_score = int(parent_score + peer_review_score)

    return max(0, final_score)


def calculate_hot_score(feed_entry, content_type_name, return_components=False):
    """
    Calculate hot score using HN-style algorithm with prioritized signals.

    Formula:
        hot_score = ((engagement_score * freshness_multiplier) /
                    (age_hours + base_hours)^gravity) * 100

    Where engagement_score is weighted sum of:
        1. Altmetric score (highest priority)
        2. Bounties (with urgency multiplier)
        3. Tips/Boosts
        4. Peer reviews
        5. Upvotes
        6. Comments

    The freshness_multiplier gives new content (especially ResearchHub posts) a
    strong time-decaying boost (4.5x → 1.0x over 48 hours) that helps new posts
    appear in trending feed before accumulating engagement signals. After 48 hours,
    all content competes on equal footing based purely on engagement and time decay.

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

        # Altmetric (external research impact)
        altmetric = get_altmetric_score(feed_entry)

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

        # Freshness multiplier (time-decaying boost for new content)
        freshness_multiplier = get_freshness_multiplier(feed_entry, age_hours)

        # ====================================================================
        # 2. Calculate engagement score using logarithmic scaling
        # ====================================================================

        config = HOT_SCORE_CONFIG["signals"]

        # Each signal is log-scaled to prevent large values from dominating
        altmetric_component = (
            math.log(altmetric + 1, config["altmetric"]["log_base"])
            * config["altmetric"]["weight"]
        )

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

        upvote_component = (
            math.log(upvote_count + 1, config["upvote"]["log_base"])
            * config["upvote"]["weight"]
        )

        comment_component = (
            math.log(comment_count + 1, config["comment"]["log_base"])
            * config["comment"]["weight"]
        )

        # Sum all components
        engagement_score = (
            altmetric_component
            + bounty_component
            + tip_component
            + peer_review_component
            + upvote_component
            + comment_component
        )

        # Apply freshness multiplier (boost new content)
        engagement_score *= freshness_multiplier

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
                    "altmetric": altmetric,
                    "bounty": bounty_amount,
                    "tip": tip_amount,
                    "peer_review": peer_review_count,
                    "upvote": upvote_count,
                    "comment": comment_count,
                },
                "components": {
                    "altmetric": altmetric_component,
                    "bounty": bounty_component,
                    "tip": tip_component,
                    "peer_review": peer_review_component,
                    "upvote": upvote_component,
                    "comment": comment_component,
                },
                "bounty_urgent": has_urgent_bounty,
                "bounty_multiplier": bounty_multiplier,
                "time_factors": {
                    "age_hours": age_hours,
                    "freshness_multiplier": freshness_multiplier,
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
