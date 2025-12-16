"""
Utility functions for extracting hot score signals from FeedEntry JSON fields.

These utilities safely extract engagement metrics from FeedEntry.content and
FeedEntry.metrics JSON fields, reducing database queries and improving performance.

All functions gracefully handle missing keys and malformed data.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


def safe_get_nested(data: dict, *keys, default=None) -> Any:
    result = data
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key)
            if result is None:
                return default
        else:
            return default
    return result


def has_comments(metrics: dict) -> bool:
    if not isinstance(metrics, dict):
        return False

    replies = safe_get_nested(metrics, "replies", default=0) or 0
    review_count = safe_get_nested(metrics, "review_metrics", "count", default=0) or 0

    return replies > 0 or review_count > 0


def get_content_type_name(feed_entry) -> str:
    try:
        return feed_entry.content_type.model.lower()
    except (AttributeError, TypeError):
        return "unknown"


def parse_iso_datetime(date_string: str) -> Optional[datetime]:
    if not date_string or not isinstance(date_string, str):
        return None

    try:
        # Handle ISO format with Z suffix
        if date_string.endswith("Z"):
            date_string = date_string[:-1] + "+00:00"

        dt = datetime.fromisoformat(date_string)

        # Ensure timezone aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Failed to parse datetime '{date_string}': {e}")
        return None


# ============================================================================
# Simple Signal Extraction Functions
# ============================================================================


def get_votes_from_metrics(metrics: dict) -> int:
    """
    Example metrics:
        {
            "votes": 5,
            "replies": 0
        }
    """
    if not isinstance(metrics, dict):
        return 0

    votes = safe_get_nested(metrics, "votes", default=0) or 0
    try:
        return int(votes)
    except (ValueError, TypeError):
        return 0


def get_peer_review_count_from_metrics(metrics: dict) -> int:
    """
    Example metrics:
        {
            "votes": 0,
            "replies": 0,
            "review_metrics": {
                "avg": 4.5,
                "count": 2
            }
        }
    """
    if not isinstance(metrics, dict):
        return 0

    count = safe_get_nested(metrics, "review_metrics", "count", default=0) or 0
    try:
        return int(count)
    except (ValueError, TypeError):
        return 0


def get_comment_count_from_metrics(metrics: dict) -> int:
    """
    Get regular comment count from metrics.

    Note: The 'replies' field already excludes peer reviews since it comes from
    get_discussion_count() which only counts GENERIC_COMMENT type comments.

    Example metrics:
        {
            "replies": 3,
            "review_metrics": {"count": 10}
        }
        → returns 3 (the replies value directly)
    """
    if not isinstance(metrics, dict):
        return 0

    replies = safe_get_nested(metrics, "replies", default=0) or 0

    try:
        return int(replies)
    except (ValueError, TypeError):
        return 0


# Social media engagement weights for calculating weighted engagement score
# Platform multipliers control relative importance: X (60%), GitHub (30%), Bluesky (10%)
SOCIAL_MEDIA_ENGAGEMENT_WEIGHTS = {
    "x": {
        "platform_multiplier": 0.6,
        "impressions": 0.1,
        "likes": 1.0,
        "replies": 2.0,
        "reposts": 3.0,
        "quotes": 5.0,
    },
    "bluesky": {
        "platform_multiplier": 0.1,
        "likes": 1.0,
        "replies": 2.0,
        "reposts": 3.0,
        "quotes": 5.0,
    },
    "github": {
        "platform_multiplier": 0.3,
        "mentions": 10.0,
    },
}


def calculate_x_engagement(x_data: dict) -> float:
    """Calculate engagement score from X/Twitter data."""
    if not x_data or not isinstance(x_data, dict):
        return 0.0

    weights = SOCIAL_MEDIA_ENGAGEMENT_WEIGHTS["x"]
    impressions = safe_get_nested(x_data, "total_impressions", default=0) or 0
    likes = safe_get_nested(x_data, "total_likes", default=0) or 0
    reposts = safe_get_nested(x_data, "total_reposts", default=0) or 0
    quotes = safe_get_nested(x_data, "total_quotes", default=0) or 0
    replies = safe_get_nested(x_data, "total_replies", default=0) or 0

    try:
        raw_score = (
            float(impressions) * weights["impressions"]
            + float(likes) * weights["likes"]
            + float(reposts) * weights["reposts"]
            + float(quotes) * weights["quotes"]
            + float(replies) * weights["replies"]
        )
        return raw_score * weights["platform_multiplier"]
    except (ValueError, TypeError):
        return 0.0


def calculate_bluesky_engagement(bluesky_data: dict) -> float:
    """Calculate engagement score from Bluesky data."""
    if not bluesky_data or not isinstance(bluesky_data, dict):
        return 0.0

    weights = SOCIAL_MEDIA_ENGAGEMENT_WEIGHTS["bluesky"]
    likes = safe_get_nested(bluesky_data, "total_likes", default=0) or 0
    reposts = safe_get_nested(bluesky_data, "total_reposts", default=0) or 0
    quotes = safe_get_nested(bluesky_data, "total_quotes", default=0) or 0
    replies = safe_get_nested(bluesky_data, "total_replies", default=0) or 0

    try:
        raw_score = (
            float(likes) * weights["likes"]
            + float(reposts) * weights["reposts"]
            + float(quotes) * weights["quotes"]
            + float(replies) * weights["replies"]
        )
        return raw_score * weights["platform_multiplier"]
    except (ValueError, TypeError):
        return 0.0


def calculate_github_engagement(github_data: dict) -> float:
    """Calculate engagement score from GitHub mentions data."""
    if not github_data or not isinstance(github_data, dict):
        return 0.0

    weights = SOCIAL_MEDIA_ENGAGEMENT_WEIGHTS["github"]
    mentions = safe_get_nested(github_data, "total_mentions", default=0) or 0

    try:
        raw_score = float(mentions) * weights["mentions"]
        return raw_score * weights["platform_multiplier"]
    except (ValueError, TypeError):
        return 0.0


def get_social_media_engagement_from_metrics(metrics: dict) -> float:
    """Extract combined social media engagement from FeedEntry metrics.

    Aggregates engagement from X/Twitter, Bluesky, and GitHub mentions.
    """
    if not isinstance(metrics, dict):
        return 0.0

    external = safe_get_nested(metrics, "external", default={})
    if not external or not isinstance(external, dict):
        return 0.0

    total = 0.0

    # X/Twitter engagement
    x_data = external.get("x", {})
    if x_data:
        total += calculate_x_engagement(x_data)

    # Bluesky engagement
    bluesky_data = external.get("bluesky", {})
    if bluesky_data:
        total += calculate_bluesky_engagement(bluesky_data)

    # GitHub mentions
    github_data = external.get("github_mentions", {})
    if github_data:
        total += calculate_github_engagement(github_data)

    return total


def calculate_adjusted_score(base_votes: int, external_metrics: dict) -> int:
    """
    Calculate vote count adjusted with social media engagement.

    Uses logarithmic scaling with multiplier of 5 for diminishing returns.

    Examples:
        base_votes=5, engagement=10   -> 5 + log(11) * 5 = 17
        base_votes=5, engagement=100  -> 5 + log(101) * 5 = 28
        base_votes=5, engagement=1000 -> 5 + log(1001) * 5 = 40
        base_votes=5, engagement=5000 -> 5 + log(5001) * 5 = 48
    """
    import math

    # Wrap external_metrics in expected format for engagement calculation
    metrics = {"external": external_metrics} if external_metrics else {}
    social_engagement = get_social_media_engagement_from_metrics(metrics)

    # Logarithmic scaling: diminishing returns, no hard cap
    social_score = int(math.log(social_engagement + 1) * 5.0)

    return base_votes + social_score


# ============================================================================
# Complex Extraction Functions
# ============================================================================


def get_bounties_from_content(
    content: dict, feed_entry, urgency_hours: int = 48
) -> Tuple[float, bool]:
    """
    Extract total bounty amount and urgency status from content JSON.

    Args:
        content: The FeedEntry.content JSON dict
        feed_entry: FeedEntry instance (for created_date fallback)
        urgency_hours: Hours threshold for urgency (default 48)

    Returns:
        Tuple of (total_amount: float, has_urgent_bounty: bool)

    Example content:
        {
            "bounties": [
                {
                    "id": 229,
                    "amount": "429.0000000000",
                    "status": "OPEN",
                    "expiration_date": "2025-10-20T20:47:34.373000Z"
                }
            ]
        }
    """
    if not isinstance(content, dict):
        return 0.0, False

    bounties = safe_get_nested(content, "bounties", default=[])
    if not isinstance(bounties, list):
        return 0.0, False

    now = datetime.now(timezone.utc)
    urgency_threshold = timedelta(hours=urgency_hours)

    total_amount = 0.0
    has_urgent_bounty = False

    for bounty in bounties:
        if not isinstance(bounty, dict):
            continue

        # Only count OPEN bounties
        status = safe_get_nested(bounty, "status", default="")
        if status != "OPEN":
            continue

        # Extract and sum amount
        amount_str = safe_get_nested(bounty, "amount", default="0")
        try:
            amount = float(amount_str)
            total_amount += amount
        except (ValueError, TypeError):
            logger.warning(f"Failed to parse bounty amount: {amount_str}")
            continue

        # Check urgency: new or expiring soon
        # Bounties don't have created_date in JSON,
        # so we use feed_entry.created_date
        time_since_create = now - feed_entry.created_date

        expiration_str = safe_get_nested(bounty, "expiration_date")
        if expiration_str:
            expiration_date = parse_iso_datetime(expiration_str)
            if expiration_date:
                time_to_expiration = expiration_date - now
                is_urgent = (
                    time_since_create < urgency_threshold
                    or time_to_expiration < urgency_threshold
                )
                if is_urgent:
                    has_urgent_bounty = True

    return total_amount, has_urgent_bounty


def get_tips_from_content(content: dict, feed_entry) -> float:
    """
    Extract total tip/boost amount from content JSON and optionally comments.

    Only queries comment tips if metrics indicate comments exist.

    Args:
        content: The FeedEntry.content JSON dict
        feed_entry: FeedEntry instance (for metrics check and lazy unified_document)

    Returns:
        Total tip amount as float

    Example content:
        {
            "purchases": [
                {
                    "id": 93,
                    "amount": "50"
                }
            ]
        }
    """
    if not isinstance(content, dict):
        return 0.0

    total = 0.0

    # Sum tips from document purchases
    purchases = safe_get_nested(content, "purchases", default=[])
    if isinstance(purchases, list):
        for purchase in purchases:
            if not isinstance(purchase, dict):
                continue

            amount_str = safe_get_nested(purchase, "amount", default="0")
            try:
                total += float(amount_str)
            except (ValueError, TypeError):
                logger.warning(f"Failed to parse purchase amount: {amount_str}")
                continue

    # Add comment tips only if comments exist
    if has_comments(feed_entry.metrics):
        # Lazy-load unified_document only when needed
        try:
            unified_document = feed_entry.unified_document
            if unified_document:
                comment_tips = unified_document.get_comment_tip_sum()
                total += comment_tips
        except Exception as e:
            logger.warning(f"Failed to get comment tip sum: {e}")

    return total


def get_upvotes_rolled_up(metrics: dict, feed_entry) -> int:
    """
    Extract total upvotes (document + comments) from metrics and optionally DB.

    Only queries comment upvotes if metrics indicate comments exist.

    Args:
        metrics: The FeedEntry.metrics JSON dict
        feed_entry: FeedEntry instance (for lazy unified_document access)

    Returns:
        Total upvote count as int

    Example metrics:
        {
            "votes": 5,
            "replies": 3
        }
    """
    total_upvotes = get_votes_from_metrics(metrics)

    # Add comment upvotes only if comments exist
    if has_comments(metrics):
        # Lazy-load unified_document only when needed
        try:
            unified_document = feed_entry.unified_document
            if unified_document:
                comment_upvotes = unified_document.get_comment_upvote_sum()
                total_upvotes += comment_upvotes
        except Exception as e:
            logger.warning(f"Failed to get comment upvote sum: {e}")

    return max(0, total_upvotes)


def get_fundraise_amount_from_content(content: dict) -> float:
    """
    Example content (PREREGISTRATION):
        {
            "fundraise": {
                "amount_raised": {
                    "rsc": 150.5,
                    "usd": 50
                }
            }
        }
    """
    if not isinstance(content, dict):
        return 0.0

    # Navigate to fundraise.amount_raised.rsc (prefer RSC over USD)
    rsc_amount = safe_get_nested(content, "fundraise", "amount_raised", "rsc")
    if rsc_amount is not None:
        try:
            return float(rsc_amount)
        except (ValueError, TypeError):
            pass

    # Fallback to USD
    usd_amount = safe_get_nested(content, "fundraise", "amount_raised", "usd")
    if usd_amount is not None:
        try:
            return float(usd_amount)
        except (ValueError, TypeError):
            pass

    return 0.0


def get_age_hours_from_content(
    content: dict,
    feed_entry,
    grant_urgency_days: int = 7,
    prereg_urgency_days: int = 7,
) -> float:
    """
    Calculate age in hours from content JSON, with urgency adjustments for
    grants/preregistrations.

    For grants with approaching deadlines: Uses end_date for urgency
    For preregistrations with approaching fundraise deadlines: Uses end_date

    Args:
        content: The FeedEntry.content JSON dict
        feed_entry: FeedEntry instance (for fallback created_date)
        grant_urgency_days: Days window for grant deadline urgency (default)
        prereg_urgency_days: Days window for preregistration urgency (default)

    Returns:
        Age in hours as float

    Example content (GRANT):
        {
            "type": "GRANT",
            "grant": {
                "end_date": "2025-08-15T07:00:00Z"
            },
            "created_date": "2025-07-16T03:25:07.738562Z"
        }
    """
    if not isinstance(content, dict):
        # Fallback to feed_entry created_date
        now = datetime.now(timezone.utc)
        age = now - feed_entry.created_date
        return max(0, age.total_seconds() / 3600)

    now = datetime.now(timezone.utc)
    doc_type = safe_get_nested(content, "type", default="")

    # Handle GRANT with approaching deadline
    if doc_type == "GRANT":
        end_date_str = safe_get_nested(content, "grant", "end_date")
        if end_date_str:
            end_date = parse_iso_datetime(end_date_str)
            if end_date:
                time_to_deadline = end_date - now
                is_urgent = (
                    timedelta(0) < time_to_deadline < timedelta(days=grant_urgency_days)
                )
                if is_urgent:
                    # Use end_date for urgency - appear "newer"
                    urgency_offset = timedelta(days=grant_urgency_days)
                    age = now - end_date + urgency_offset
                    return max(0, age.total_seconds() / 3600)

    # Handle PREREGISTRATION with approaching fundraise deadline
    if doc_type == "PREREGISTRATION":
        fundraise_end_str = safe_get_nested(content, "fundraise", "end_date")
        if fundraise_end_str:
            fundraise_end = parse_iso_datetime(fundraise_end_str)
            if fundraise_end:
                time_to_deadline = fundraise_end - now
                is_urgent = (
                    timedelta(0)
                    < time_to_deadline
                    < timedelta(days=prereg_urgency_days)
                )
                if is_urgent:
                    # Use end_date for urgency
                    urgency_offset = timedelta(days=prereg_urgency_days)
                    age = now - fundraise_end + urgency_offset
                    return max(0, age.total_seconds() / 3600)

    # Default: use created_date from content or feed_entry
    created_date_str = safe_get_nested(content, "created_date")
    if created_date_str:
        created_date = parse_iso_datetime(created_date_str)
        if created_date:
            age = now - created_date
            return max(0, age.total_seconds() / 3600)

    # Ultimate fallback: feed_entry.created_date
    age = now - feed_entry.created_date
    return max(0, age.total_seconds() / 3600)
