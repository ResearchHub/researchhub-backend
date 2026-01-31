from django.db import models


class Leaderboard(models.Model):
    """
    Pre-computed leaderboard data for both funders and earners.
    Refreshed periodically via Celery task to avoid expensive on-the-fly queries.
    """

    # Leaderboard type choices
    FUNDER = "FUNDER"
    EARNER = "EARNER"

    LEADERBOARD_TYPE_CHOICES = [
        (FUNDER, "Funder"),
        (EARNER, "Earner"),
    ]

    # Period choices
    SEVEN_DAYS = "7_DAYS"
    THIRTY_DAYS = "30_DAYS"
    SIX_MONTHS = "6_MONTHS"
    ONE_YEAR = "1_YEAR"
    ALL_TIME = "ALL_TIME"

    PERIOD_CHOICES = [
        (SEVEN_DAYS, "7 Days"),
        (THIRTY_DAYS, "30 Days"),
        (SIX_MONTHS, "6 Months"),
        (ONE_YEAR, "1 Year"),
        (ALL_TIME, "All Time"),
    ]

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="leaderboard_entries",
        help_text="The user this leaderboard entry belongs to",
    )
    leaderboard_type = models.CharField(
        max_length=16,
        choices=LEADERBOARD_TYPE_CHOICES,
        help_text="Type of leaderboard (funder or earner)",
    )
    period = models.CharField(
        max_length=16,
        choices=PERIOD_CHOICES,
        help_text="Time period for the leaderboard",
    )
    rank = models.PositiveIntegerField(
        help_text="User's rank in this leaderboard",
    )
    total_amount = models.DecimalField(
        max_digits=19,
        decimal_places=8,
        help_text="Total RSC amount for ranking",
    )

    computed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this leaderboard entry was computed",
    )

    class Meta:
        verbose_name = "Leaderboard"
        verbose_name_plural = "Leaderboards"
        indexes = [
            models.Index(
                fields=["leaderboard_type", "period", "rank"],
                name="lb_type_period_rank_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "leaderboard_type", "period"],
                name="unique_user_leaderboard_period",
            ),
        ]

    def __str__(self):
        return (
            f"Leaderboard: {self.user_id} - {self.leaderboard_type} - "
            f"{self.period} - Rank {self.rank}"
        )
