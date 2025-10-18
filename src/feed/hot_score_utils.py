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


def get_altmetric_from_metrics(metrics: dict) -> float:
    """
    Example metrics:
        {
            "votes": 0,
            "altmetric_score": 1.75,
            "twitter_count": 4
        }
    """
    if not isinstance(metrics, dict):
        return 0.0

    score = safe_get_nested(metrics, "altmetric_score", default=0)
    try:
        return float(score) if score else 0.0
    except (ValueError, TypeError):
        return 0.0


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
    Example metrics:
        {
            "replies": 5,
            "review_metrics": {"count": 2}
        }
        → returns 3 (5 - 2)
    """
    if not isinstance(metrics, dict):
        return 0

    replies = safe_get_nested(metrics, "replies", default=0) or 0
    review_count = safe_get_nested(metrics, "review_metrics", "count", default=0) or 0

    try:
        return max(0, int(replies) - int(review_count))
    except (ValueError, TypeError):
        return 0


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


def get_tips_from_content(content: dict, feed_entry, unified_document) -> float:
    """
    Extract total tip/boost amount from content JSON and optionally comments.

    Only queries comment tips if metrics indicate comments exist.

    Args:
        content: The FeedEntry.content JSON dict
        feed_entry: FeedEntry instance (for metrics check)
        unified_document: ResearchhubUnifiedDocument instance (for comment tips)

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
    if unified_document and has_comments(feed_entry.metrics):
        try:
            comment_tips = unified_document.get_comment_tip_sum()
            total += comment_tips
        except Exception as e:
            logger.warning(f"Failed to get comment tip sum: {e}")

    return total


def get_upvotes_rolled_up(metrics: dict, feed_entry, unified_document) -> int:
    """
    Example metrics:
        {
            "votes": 5,
            "replies": 3
        }
    """
    total_upvotes = get_votes_from_metrics(metrics)

    # Add comment upvotes only if comments exist
    if unified_document and has_comments(metrics):
        try:
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
