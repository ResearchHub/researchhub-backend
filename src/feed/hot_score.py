"""
Hot Score Implementation for Feed Entry Ranking

Calculates content-type specific hot scores for ranking feed entries.
"""

import math
from datetime import datetime, timezone

# Content Type Weights
# These weights will be used to adjust the importance of different signals
# based on content type
#    - vote_weight: Base vote weight (upvotes - downvotes)
#    - discussion_weight: Weight for discussions/comments
#    - citation_weight: Weight for citations (paper-specific)
#    - download_weight: Weight for downloads (paper-specific)
#    - bounty_weight: Weight for bounties
#    - time_decay_factor: How quickly score decays with time
#    - half_life_days: Decay half-life in days
CONTENT_TYPE_WEIGHTS = {
    "paper": {
        "vote_weight": 1.0,
        "discussion_weight": 0.5,
        "citation_weight": 2.0,
        "download_weight": 0.3,
        "bounty_weight": 1.5,
        "time_decay_factor": 0.85,
        "half_life_days": 7,
    },
    "researchhubpost": {
        "vote_weight": 1.0,
        "discussion_weight": 1.0,
        "bounty_weight": 2.0,
        "time_decay_factor": 0.90,
        "half_life_days": 3,
    },
    "rhcommentmodel": {
        "vote_weight": 1.0,
        "reply_weight": 1.2,
        "bounty_weight": 2.5,
        "time_decay_factor": 0.95,
        "half_life_days": 2,
    },
}


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
    discussion_count = getattr(item, "discussion_count", 0) or 0
    created_date = getattr(item, "created_date", datetime.now(timezone.utc))

    # Get bounty amount
    bounty_amount = 0
    if hasattr(item, "bounties"):
        try:
            bounty_amount = sum(bounty.amount for bounty in item.bounties.all())
        except Exception:
            pass

    # Calculate base score components
    vote_component = vote_score * weights.get("vote_weight", 1.0)
    discussion_component = (
        math.log(discussion_count + 1) * weights.get("discussion_weight", 0.5) * 10
    )
    bounty_component = math.sqrt(bounty_amount) * weights.get("bounty_weight", 1.5)

    score = vote_component + discussion_component + bounty_component

    # Apply time decay
    half_life_seconds = weights.get("half_life_days", 7) * 24 * 60 * 60

    # Parse string date if needed
    if isinstance(created_date, str):
        created_date = datetime.fromisoformat(created_date.replace("Z", "+00:00"))

    # Calculate age and apply decay
    age_seconds = (datetime.now(timezone.utc) - created_date).total_seconds()
    time_decay = math.pow(2, -age_seconds / half_life_seconds)

    # Calculate final score with time decay
    final_score = int(score * time_decay)

    # Ensure score is at least 1 for valid content
    return max(1, final_score)
