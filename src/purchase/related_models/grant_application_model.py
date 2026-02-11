from django.db import models
from django.db.models import CASCADE

from utils.models import DefaultModel


class GrantApplicationQuerySet(models.QuerySet):
    """QuerySet for GrantApplication with common filters."""

    def for_user_grants(self, user):
        """Filter applications for grants created by the given user."""
        return self.filter(grant__created_by=user)

    def fundraise_ids(self) -> set[int]:
        """Return set of fundraise IDs for these applications."""
        return set(
            self.values_list(
                "preregistration_post__unified_document__fundraises__id", flat=True
            )
        )


class GrantApplication(DefaultModel):
    """Simple linking model between grants and preregistration posts."""

    objects = GrantApplicationQuerySet.as_manager()

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

    class Meta:
        unique_together = ("grant", "preregistration_post")
        indexes = [
            models.Index(fields=["grant"]),
            models.Index(fields=["applicant"]),
        ]

    def __str__(self):
        return f"Grant Application: {self.grant} - {self.preregistration_post}"
