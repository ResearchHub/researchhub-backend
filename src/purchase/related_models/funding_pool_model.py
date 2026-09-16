from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import DecimalField, Sum
from django.db.models.functions import Cast

from purchase.related_models.purchase_model import Purchase
from utils.models import DefaultModel

if TYPE_CHECKING:
    # Provides a hint to mypy that User is available in this module to avoid error
    from user.models import User

# Purchase.amount is stored as text; cast it before summing.
RSC_AMOUNT_FIELD = DecimalField(max_digits=19, decimal_places=10)


class FundingPoolContributor(TypedDict):
    user: "User"
    total_rsc: Decimal


class FundingPoolContributorsSummary(TypedDict):
    total: int
    top: list[FundingPoolContributor]


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

    def get_contributors_summary(
        self, limit: int = 5
    ) -> FundingPoolContributorsSummary:
        """Rank contributors by total RSC given; ``top`` holds the first ``limit``."""
        from user.models import User

        totals_by_user = (
            self.purchases.filter(
                purchase_type=Purchase.FUNDING_POOL_CONTRIBUTION,
                paid_status=Purchase.PAID,
            )
            .values("user_id")
            .annotate(total_rsc=Sum(Cast("amount", RSC_AMOUNT_FIELD)))
            .order_by("-total_rsc")
        )
        top_rows = list(totals_by_user[:limit])
        users = User.objects.select_related("author_profile").in_bulk(
            [row["user_id"] for row in top_rows]
        )

        return {
            "total": totals_by_user.count(),
            "top": [
                {"user": users[row["user_id"]], "total_rsc": row["total_rsc"]}
                for row in top_rows
            ],
        }

    @property
    def is_valid_for_contribution(self) -> bool:
        """Whether the pool currently accepts contributions."""
        return self.status == self.OPEN and self.grant.is_active()

    @property
    def is_valid_for_distribution(self) -> bool:
        """Whether holdings can be distributed to proposal fundraises."""
        return self.status == self.OPEN
