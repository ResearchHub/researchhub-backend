"""
Comment Scoring Utilities

Provides scoring algorithms for ranking comments, following the architectural
pattern established by feed.hot_score module.
"""

from django.db.models import (
    Case,
    DecimalField,
    F,
    FloatField,
    IntegerField,
    Q,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, Extract, Greatest, Ln, Power
from django.utils import timezone

from reputation.models import Bounty

BEST_SCORE_CONFIG = {
    "signals": {
        "bounty": {"weight": 80.0},
        "accepted_answer": {"weight": 100.0},
        "score": {"weight": 20.0},
    },
    "time_decay": {
        "gravity": 1.5,
        "base_hours": 10.0,
    },
    "deleted_sentinel": -999999.0,
}


def annotate_best_score(queryset: QuerySet) -> QuerySet:
    """
    Annotate queryset with hot-score inspired best_score for comment sorting.

    Uses logarithmic scaling and time decay similar to feed hot_score algorithm.
    Deleted comments (is_removed=True) are always scored last.

    Formula:
        engagement_score = (
            ln(bounty_sum + 1) * 80.0 +
            accepted_answer * 100.0 +
            ln(score + 1) * 20.0
        )
        best_score = engagement_score / (age_hours + 10)^1.5

    Args:
        queryset: RhCommentModel queryset

    Returns:
        Annotated queryset with 'best_score' field
    Issues: 
        I removed the tip component from the BEST_SCORE_CONFIG because it was not working as expected.  It being stored as a string was causing issues.
    """
    config = BEST_SCORE_CONFIG
    
    # ========================================================================
    # 1. Annotate base fields (bounty_sum, accepted_answer)
    # ========================================================================
    queryset = queryset.annotate(
        bounty_sum=Coalesce(
            Sum("bounties__amount", filter=Q(bounties__status=Bounty.OPEN)),
            0,
            output_field=DecimalField(),
        ),
        accepted_answer=Cast("is_accepted_answer", output_field=IntegerField()),
    )

    # ========================================================================
    # 2. Calculate time-based components
    # ========================================================================
    age_seconds = Extract(timezone.now() - F("created_date"), "epoch")
    age_hours = age_seconds / 3600.0

    # ========================================================================
    # 3. Calculate engagement score (weighted sum of log-scaled signals)
    # ========================================================================
    bounty_component = (
        Ln(Greatest(F("bounty_sum") + 1, Value(1)))
        * config["signals"]["bounty"]["weight"]
    )
    accepted_component = (
        F("accepted_answer") * config["signals"]["accepted_answer"]["weight"]
    )
    score_component = (
        Ln(Greatest(F("score") + 1, Value(1)))
        * config["signals"]["score"]["weight"]
    )

    engagement_score = bounty_component + accepted_component + score_component

    # ========================================================================
    # 4. Apply time decay and handle deleted comments
    # ========================================================================
    time_denominator = Power(
        age_hours + config["time_decay"]["base_hours"],
        config["time_decay"]["gravity"],
    )
    raw_best_score = engagement_score / time_denominator

    return queryset.annotate(
        best_score=Case(
            When(is_removed=True, then=Value(config["deleted_sentinel"])),
            default=raw_best_score,
            output_field=FloatField(),
        )
    )

