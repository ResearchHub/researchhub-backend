from django.db import models
from django.db.models import CASCADE
from django.utils.translation import gettext_lazy as _

from utils.models import DefaultModel


class GrantApplicationStatus(models.TextChoices):
    """
    The grant application status which can be pending, approved, or rejected.
    """

    PENDING = "PENDING", _("Pending")
    APPROVED = "APPROVED", _("Approved")
    REJECTED = "REJECTED", _("Rejected")


class GrantApplication(DefaultModel):
    """Simple linking model between grants and preregistration posts."""

    grant = models.ForeignKey(
        "purchase.Grant", on_delete=CASCADE, related_name="applications"
    )

    preregistration_post = models.ForeignKey(
        "researchhub_document.ResearchhubPost",
        on_delete=CASCADE,
        related_name="grant_applications",
    )

    applicant = models.ForeignKey(
        "user.User", on_delete=CASCADE, related_name="grant_applications"
    )

    status = models.CharField(
        choices=GrantApplicationStatus.choices,
        default=GrantApplicationStatus.PENDING,
    )

    class Meta:
        unique_together = ("grant", "preregistration_post")
        indexes = [
            models.Index(fields=["grant"]),
            models.Index(fields=["applicant"]),
        ]

    def __str__(self):
        return f"Grant Application: {self.grant} - {self.preregistration_post}"
