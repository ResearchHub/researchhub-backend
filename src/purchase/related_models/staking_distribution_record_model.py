from django.db import models

from utils.models import DefaultModel


class StakingDistributionRecord(DefaultModel):
    """
    Record of each staking reward distribution cycle.
    Used for audit trail and to prevent duplicate distributions.

    Each week, the system distributes funding credits from a fixed pool
    to all stakers proportional to their weighted RSC holdings.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    distribution_date = models.DateField(
        unique=True,
        help_text="The date this distribution was executed",
    )

    # Total credits in the distribution pool for this cycle
    total_pool_amount = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        help_text="Total funding credits available for distribution",
    )

    # Aggregates for this distribution
    total_weighted_balance = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        help_text="Sum of all users' weighted balances",
    )
    users_rewarded = models.PositiveIntegerField(
        default=0,
        help_text="Number of users who received rewards",
    )

    # Status tracking
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Error message if distribution failed",
    )

    class Meta:
        indexes = [
            models.Index(fields=["distribution_date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"StakingDistributionRecord({self.distribution_date}, {self.status})"
