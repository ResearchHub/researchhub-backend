from django.db import models
from django.db.models import CASCADE

from purchase.related_models.constants.currency import USD
from utils.models import DefaultModel


class Grant(DefaultModel):
    """
    Model representing a grant provided by an organization or individual.
    Unlike fundraises (seeking funding), grants represent money being given
    to support research initiatives.
    """

    # Status choices
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"

    STATUS_CHOICES = (
        (OPEN, "Open"),
        (CLOSED, "Closed"),
        (COMPLETED, "Completed"),
    )

    # Foreign key relationships
    created_by = models.ForeignKey(
        "user.User",
        on_delete=CASCADE,
        related_name="grants",
        help_text="User who created this grant entry",
    )
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        on_delete=CASCADE,
        related_name="grants",
        help_text="Associated unified document",
    )

    # Grant-specific fields
    amount = models.DecimalField(
        decimal_places=2, max_digits=19, help_text="Total grant amount being provided"
    )
    currency = models.CharField(
        max_length=16, default=USD, help_text="Currency of the grant amount"
    )
    organization = models.CharField(
        max_length=255, help_text="Name of the granting organization"
    )
    description = models.TextField(
        help_text="Grant description, requirements, and application details"
    )
    status = models.CharField(
        choices=STATUS_CHOICES,
        default=OPEN,
        max_length=32,
        help_text="Current status of the grant",
    )

    # Time fields
    start_date = models.DateTimeField(
        auto_now_add=True, help_text="When the grant was first posted"
    )
    end_date = models.DateTimeField(
        blank=True, null=True, help_text="Deadline for grant applications"
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["organization"]),
            models.Index(fields=["end_date"]),
        ]

    def __str__(self):
        return f"{self.organization} - {self.amount} {self.currency}"

    def is_expired(self):
        """Check if the grant application deadline has passed"""
        if self.end_date:
            from datetime import datetime

            import pytz

            return self.end_date < datetime.now(pytz.UTC)
        return False

    def is_active(self):
        """Check if the grant is currently accepting applications"""
        return self.status == self.OPEN and not self.is_expired()
