from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import DefaultModel


class UsdBalance(DefaultModel):
    """
    Transaction-based USD balance tracking.
    Each record represents a credit (positive) or debit (negative) in cents.
    The user's total balance is the sum of all their UsdBalance amounts.
    """

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="usd_balances"
    )
    amount_cents = models.IntegerField(
        help_text="Amount in cents. Positive = credit, negative = debit"
    )

    # Generic foreign key to track source of transaction
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    source = GenericForeignKey("content_type", "object_id")

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["created_date"]),
        ]
