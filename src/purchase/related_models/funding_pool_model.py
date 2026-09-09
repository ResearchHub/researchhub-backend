from decimal import Decimal

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from utils.models import DefaultModel


class FundingPool(DefaultModel):
    """Community contribution pot attached to a Grant (RFP).

    Contributors deposit RSC into the pool; the grant creator distributes
    holdings to proposal fundraises. One pool per grant.
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STATUS_CHOICES = (
        (OPEN, OPEN),
        (CLOSED, CLOSED),
    )

    grant = models.OneToOneField(
        "purchase.Grant",
        on_delete=models.CASCADE,
        related_name="funding_pool",
        db_comment="Grant this pool belongs to (one pool per grant)",
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="funding_pools",
        db_comment="Grant creator at pool creation time",
    )
    amount_holding = models.DecimalField(
        default=0,
        decimal_places=10,
        max_digits=19,
        db_comment="RSC currently held in the pool and available to distribute",
    )
    amount_distributed = models.DecimalField(
        default=0,
        decimal_places=10,
        max_digits=19,
        db_comment="RSC distributed from the pool into proposal fundraises",
    )
    status = models.CharField(
        choices=STATUS_CHOICES,
        default=OPEN,
        max_length=32,
        db_comment="Whether the pool accepts contributions and distributions",
    )
    purchases = GenericRelation(
        "purchase.Purchase",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="funding_pool",
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"], name="purchase_fu_status_pool_idx"),
        ]

    def __str__(self):
        return f"FundingPool(grant={self.grant_id}, holding={self.amount_holding})"

    @property
    def amount_raised(self) -> Decimal:
        """Total RSC ever contributed: holding + distributed."""
        return self.amount_holding + self.amount_distributed

    @property
    def is_valid_for_contribution(self) -> bool:
        """Whether the pool currently accepts contributions."""
        return self.status == self.OPEN and self.grant.is_active()

    @property
    def is_valid_for_distribution(self) -> bool:
        """Whether holdings can be distributed to proposal fundraises."""
        return self.status == self.OPEN
