"""
Hot Score Implementation for Feed Entry Ranking

Calculates hot scores for feed entries using a declarative, Hacker News-style algorithm.
The algorithm prioritizes content based on:
1. Altmetric score (external engagement metrics)
2. Bounties (especially new or expiring within 24h)
3. Tips/Boosts (financial support)
4. Peer reviews (expert feedback)
5. Upvotes (community engagement)
6. Comments (discussion activity)
7. Recency (time decay with polynomial function)

Hot Score Formula:
    hot_score = ((engagement_score * content_multiplier) /
                 (age_in_hours + base_hours)^gravity) * 100

Where engagement_score is a weighted sum of logarithmic-scaled signals.

Note: Scores are scaled by 100 and converted to integers to preserve precision
while allowing meaningful differentiation between items during sorting.
"""

import logging
import math
from datetime import datetime, timedelta, timezone

from django.contrib.contenttypes.models import ContentType
from django.db.models import DecimalField, Sum
from django.db.models.functions import Cast

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
# This declarative structure defines all weights and parameters for hot score
HOT_SCORE_CONFIG = {
    # Signal weights determine relative importance of each engagement metric
    # Higher weight = more influence on final score
    "signals": {
        "altmetric": {
            "weight": 100.0,  # Highest priority - external impact
            "log_base": math.e,  # Natural log for smooth scaling
        },
        "bounty": {
            "weight": 80.0,
            "log_base": math.e,
            "urgency_multiplier": 1.5,  # Boost for new/expiring
            "urgency_hours": 24,
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
    # Content type multipliers favor platform-native content
    "content_multipliers": {
        "researchhubpost": 1.5,  # Boost ResearchHub-native content
        "paper": 1.0,  # External papers at baseline
    },
    # Special document type handling
    "document_types": {
        "grant_urgency_days": 7,  # Grant deadline urgency
        "preregistration_urgency_days": 7,  # Preregistration urgency
    },
}


# ============================================================================
# Signal Aggregation Helper Functions
# ============================================================================


def get_altmetric_score(item):
    """
    Extract altmetric score from Paper.external_metadata.

    Args:
        item: The content item (Paper or ResearchhubPost)

    Returns:
        float: Altmetric score, or 0 if not available
    """
    if not isinstance(item, Paper):
        return 0

    if not hasattr(item, "external_metadata") or not item.external_metadata:
        return 0

    # Safely navigate the nested dictionary structure
    metrics = item.external_metadata.get("metrics")
    if not metrics or not isinstance(metrics, dict):
        return 0

    score = metrics.get("score", 0)
    try:
        return float(score) if score else 0
    except (ValueError, TypeError):
        return 0


def get_total_bounty_amount(unified_document):
    """
    Sum all open bounties on the document and its comments.

    Args:
        unified_document: ResearchhubUnifiedDocument instance

    Returns:
        tuple: (total_amount: float, has_urgent_bounty: bool)
    """
    from reputation.related_models.bounty import Bounty

    if not unified_document:
        return 0, False

    now = datetime.now(timezone.utc)
    urgency_hours = HOT_SCORE_CONFIG["signals"]["bounty"]["urgency_hours"]
    urgency_threshold = timedelta(hours=urgency_hours)

    # Get all open bounties on this unified document
    bounties = unified_document.related_bounties.filter(status=Bounty.OPEN)

    total_amount = 0
    has_urgent_bounty = False

    for bounty in bounties:
        try:
            amount = float(bounty.amount)
            total_amount += amount

            # Check if bounty is new or expiring soon
            time_since_create = now - bounty.created_date
            if bounty.expiration_date:
                time_to_expiration = bounty.expiration_date - now
                is_urgent = (
                    time_since_create < urgency_threshold
                    or time_to_expiration < urgency_threshold
                )
                if is_urgent:
                    has_urgent_bounty = True
        except (ValueError, TypeError, AttributeError):
            continue

    return total_amount, has_urgent_bounty


def get_total_tip_amount(unified_document, item):
    """
    Sum all tips/boosts (Purchase.BOOST) on the document and its comments.

    Args:
        unified_document: ResearchhubUnifiedDocument instance
        item: The content item (Paper or ResearchhubPost)

    Returns:
        float: Total tip amount
    """
    from purchase.models import Purchase

    total = 0

    # Get tips on the main item
    if hasattr(item, "purchases"):
        item_tips = item.purchases.filter(
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=10)))
        )[
            "total"
        ]

        if item_tips:
            try:
                total += float(item_tips)
            except (ValueError, TypeError):
                pass

    # Get tips on comments using unified document helper method
    if unified_document:
        comment_tips = unified_document.get_comment_tip_sum()
        total += comment_tips

    return total


def get_total_upvotes(item, unified_document):
    """
    Calculate total upvotes: document upvotes + rolled-up comment upvotes.

    Args:
        item: The content item (Paper or ResearchhubPost)
        unified_document: ResearchhubUnifiedDocument instance

    Returns:
        int: Total upvote count
    """
    # Start with document-level score (upvotes - downvotes)
    total_upvotes = getattr(item, "score", 0) or 0

    # Add comment upvotes using unified document helper method
    if unified_document:
        comment_upvotes = unified_document.get_comment_upvote_sum()
        total_upvotes += comment_upvotes

    return max(0, total_upvotes)  # Ensure non-negative


def get_peer_review_count(unified_document):
    """
    Count peer reviews on the document.

    Args:
        unified_document: ResearchhubUnifiedDocument instance

    Returns:
        int: Number of peer reviews
    """
    if not unified_document:
        return 0

    return unified_document.get_peer_review_comments().count()


def get_comment_count(item, unified_document):
    """
    Count regular comments (excluding peer reviews).

    Args:
        item: The content item (Paper or ResearchhubPost)
        unified_document: ResearchhubUnifiedDocument instance

    Returns:
        int: Number of comments
    """
    # Try to use cached discussion_count first
    if hasattr(item, "discussion_count"):
        discussion_count = getattr(item, "discussion_count", 0) or 0
        # Subtract peer reviews to avoid double counting
        peer_reviews = get_peer_review_count(unified_document)
        return max(0, discussion_count - peer_reviews)

    # Fallback: count from unified document helper method
    if unified_document:
        return unified_document.get_regular_comments().count()

    return 0


def get_age_hours(item):
    """
    Calculate age in hours based on content type and document type.

    For Papers: Use paper_publish_date if available, else created_date
    For Posts:
        - GRANT: Use end_date if within urgency window
        - PREREGISTRATION: Use fundraise.end_date if within urgency
        - Others: Use created_date

    Args:
        item: The content item (Paper or ResearchhubPost)

    Returns:
        float: Age in hours
    """
    now = datetime.now(timezone.utc)

    # Handle Papers
    if isinstance(item, Paper):
        publish_date = getattr(item, "paper_publish_date", None)
        if publish_date:
            age = now - publish_date
            return max(0, age.total_seconds() / 3600)

        # Fallback to created_date
        created_date = getattr(item, "created_date", now)
        age = now - created_date
        return max(0, age.total_seconds() / 3600)

    # Handle ResearchhubPost
    if isinstance(item, ResearchhubPost):
        document_type = getattr(item, "document_type", None)

        # Handle GRANT - use end_date if approaching
        if document_type == "GRANT":
            unified_doc = getattr(item, "unified_document", None)
            if unified_doc and hasattr(unified_doc, "grants"):
                grant = unified_doc.grants.first()
                if grant and grant.end_date:
                    config = HOT_SCORE_CONFIG["document_types"]
                    urgency_days = config["grant_urgency_days"]
                    time_to_deadline = grant.end_date - now
                    is_urgent = (
                        timedelta(0) < time_to_deadline < timedelta(days=urgency_days)
                    )
                    if is_urgent:
                        # Use end_date for urgency - appear "newer"
                        urgency_offset = timedelta(days=urgency_days)
                        age = now - grant.end_date + urgency_offset
                        return max(0, age.total_seconds() / 3600)

        # Handle PREREGISTRATION - use fundraise end_date if approaching
        if document_type == "PREREGISTRATION":
            unified_doc = getattr(item, "unified_document", None)
            if unified_doc and hasattr(unified_doc, "fundraises"):
                fundraise = unified_doc.fundraises.filter(status="OPEN").first()
                if fundraise and fundraise.end_date:
                    config = HOT_SCORE_CONFIG["document_types"]
                    urgency_days = config["preregistration_urgency_days"]
                    time_to_deadline = fundraise.end_date - now
                    is_urgent = (
                        timedelta(0) < time_to_deadline < timedelta(days=urgency_days)
                    )
                    if is_urgent:
                        # Use end_date for urgency
                        urgency_offset = timedelta(days=urgency_days)
                        age = now - fundraise.end_date + urgency_offset
                        return max(0, age.total_seconds() / 3600)

    # Default: use created_date
    created_date = getattr(item, "created_date", now)
    age = now - created_date
    return max(0, age.total_seconds() / 3600)


def get_content_type_multiplier(item):
    """
    Get content type multiplier to favor ResearchHub-native content.

    Args:
        item: The content item (Paper or ResearchhubPost)

    Returns:
        float: Multiplier (e.g., 1.2 for Posts, 1.0 for Papers)
    """
    if isinstance(item, ResearchhubPost):
        return HOT_SCORE_CONFIG["content_multipliers"]["researchhubpost"]
    elif isinstance(item, Paper):
        return HOT_SCORE_CONFIG["content_multipliers"]["paper"]

    return 1.0  # Default


def get_fundraise_amount(item):
    """
    Get fundraise amount for PREREGISTRATION posts.

    Args:
        item: The content item

    Returns:
        float: Amount raised, or 0 if not applicable
    """
    if not isinstance(item, ResearchhubPost):
        return 0

    document_type = getattr(item, "document_type", None)
    if document_type != "PREREGISTRATION":
        return 0

    unified_doc = getattr(item, "unified_document", None)
    if not unified_doc or not hasattr(unified_doc, "fundraises"):
        return 0

    fundraise = unified_doc.fundraises.filter(status="OPEN").first()
    if not fundraise:
        return 0

    try:
        amount = fundraise.get_amount_raised()
        return float(amount) if amount else 0
    except (ValueError, TypeError, AttributeError):
        return 0


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


def calculate_hot_score(feed_entry, content_type_name):
    """
    Calculate hot score using HN-style algorithm with prioritized signals.

    Formula:
        hot_score = ((engagement_score * content_multiplier) /
                    (age_hours + base_hours)^gravity) * 100

    Where engagement_score is weighted sum of:
        1. Altmetric score (highest priority)
        2. Bounties (with urgency multiplier)
        3. Tips/Boosts
        4. Peer reviews
        5. Upvotes
        6. Comments

    The final score is scaled by 100 and converted to an integer to preserve
    precision while allowing meaningful differentiation between items.

    Args:
        feed_entry: The feed entry object
        content_type_name: ContentType instance

    Returns:
        int: Calculated hot score (scaled by 100)
    """
    item = feed_entry.item
    unified_document = feed_entry.unified_document

    if not item:
        return 0

    try:
        # ====================================================================
        # 1. Gather all signals
        # ====================================================================

        # Altmetric (external research impact)
        altmetric = get_altmetric_score(item)

        # Bounties (with urgency detection)
        bounty_amount, has_urgent_bounty = get_total_bounty_amount(unified_document)

        # Tips/Boosts
        tip_amount = get_total_tip_amount(unified_document, item)

        # Peer reviews
        peer_review_count = get_peer_review_count(unified_document)

        # Upvotes (document + comments rolled up)
        upvote_count = get_total_upvotes(item, unified_document)

        # Comments (excluding peer reviews)
        comment_count = get_comment_count(item, unified_document)

        # Fundraise amount (for PREREGISTRATION)
        fundraise_amount = get_fundraise_amount(item)
        if fundraise_amount > 0:
            # Treat fundraise amount like tips
            tip_amount += fundraise_amount

        # Age in hours
        age_hours = get_age_hours(item)

        # Content type multiplier
        content_multiplier = get_content_type_multiplier(item)

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

        # Apply content type multiplier (favor ResearchHub content)
        engagement_score *= content_multiplier

        # ====================================================================
        # 3. Apply HN-style time decay
        # ====================================================================

        decay_config = HOT_SCORE_CONFIG["time_decay"]
        gravity = decay_config["gravity"]
        base_hours = decay_config["base_hours"]

        # Denominator grows polynomially with age, drastically reducing score over time
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
        return max(0, int(scaled_score))

    except Exception as e:
        logger.error(f"Error calculating hot score for feed_entry {feed_entry.id}: {e}")
        sentry.log_error(e)
        return 0  # Return 0 on error (was 1 before scaling)
