from django.db import models

from utils.models import DefaultModel


class PourReviewPuzzle(DefaultModel):
    """A daily puzzle where the largest flask starts full and the rest start empty."""

    date = models.DateField(unique=True)
    flasks = models.JSONField(db_comment="Flask capacities in mL, largest first.")
    target_amount = models.PositiveSmallIntegerField()
    target_count = models.PositiveSmallIntegerField(
        db_comment="How many flasks must hold the target amount."
    )
    par = models.PositiveSmallIntegerField(
        db_comment="Fewest pours that solve the puzzle."
    )


class PourReviewResult(DefaultModel):
    """A user's solution to a daily puzzle."""

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="pour_review_results",
    )
    puzzle = models.ForeignKey(
        PourReviewPuzzle,
        on_delete=models.CASCADE,
        related_name="results",
    )
    pours = models.JSONField(db_comment="Ordered [source, target] flask indexes.")
    pour_count = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "puzzle"],
                name="unique_pour_review_result_per_puzzle",
            )
        ]
