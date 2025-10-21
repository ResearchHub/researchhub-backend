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

from purchase.models import Purchase
from reputation.models import Bounty
from user.related_models.user_verification_model import UserVerification

BEST_SCORE_CONFIG = {
    "signals": {
        "accepted_answer": {"weight": 100.0},
        "user_verified": {"weight": 90.0},
        "bounty": {"weight": 80.0},
        "tip": {"weight": 60.0},
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
            accepted_answer * 100.0 +
            user_verified * 90.0 +
            ln(bounty_sum + 1) * 80.0 +
            ln(tip_sum + 1) * 60.0 +
            ln(score + 1) * 20.0
        )
        best_score = engagement_score / (age_hours + 10)^1.5

    Args:
        queryset: RhCommentModel queryset

    Returns:
        Annotated queryset with 'best_score' field
    """
    config = BEST_SCORE_CONFIG
    
    # ========================================================================
    # 1. Annotate base fields
    # ========================================================================
    
    # Pre-calculate simple fields
    accepted_answer_int = Cast("is_accepted_answer", output_field=IntegerField())
    
    # Use CASE/WHEN with LEFT JOIN instead of Exists subquery for better performance
    user_verified_int = Case(
        When(
            created_by__userverification__status=UserVerification.Status.APPROVED,
            then=Value(1),
        ),
        default=Value(0),
        output_field=IntegerField(),
    )
    
    # Calculate aggregated sums (these trigger joins)
    bounty_sum = Coalesce(
        Sum("bounties__amount", filter=Q(bounties__status=Bounty.OPEN)),
        0,
        output_field=DecimalField(),
    )
    tip_sum = Coalesce(
        Sum(
            Cast(
                "purchases__amount",
                output_field=DecimalField(max_digits=19, decimal_places=8),
            ),
            filter=Q(
                purchases__paid_status=Purchase.PAID,
                purchases__purchase_type=Purchase.BOOST,
            ),
        ),
        0,
        output_field=DecimalField(),
    )
    
    # Split into separate annotate() calls to avoid Cartesian product
    # when aggregating multiple GenericRelations
    queryset = queryset.annotate(
        accepted_answer=accepted_answer_int,
        user_verified=user_verified_int,
    ).annotate(
        bounty_sum=bounty_sum,
    ).annotate(
        tip_sum=tip_sum,
    )

    # ========================================================================
    # 2. Calculate time-based components
    # ========================================================================
    age_seconds = Extract(timezone.now() - F("created_date"), "epoch")
    age_hours = age_seconds / 3600.0

    # ========================================================================
    # 3. Calculate engagement score (weighted sum of log-scaled signals)
    # ========================================================================
    accepted_component = (
        F("accepted_answer") * config["signals"]["accepted_answer"]["weight"]
    )
    verified_component = F("user_verified") * config["signals"]["user_verified"]["weight"]
    bounty_component = (
        Ln(Greatest(F("bounty_sum") + 1, Value(1)))
        * config["signals"]["bounty"]["weight"]
    )
    tip_component = (
        Ln(Greatest(F("tip_sum") + 1, Value(1))) * config["signals"]["tip"]["weight"]
    )
    score_component = (
        Ln(Greatest(F("score") + 1, Value(1)))
        * config["signals"]["score"]["weight"]
    )

    engagement_score = (
        accepted_component
        + verified_component
        + bounty_component
        + tip_component
        + score_component
    )

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

