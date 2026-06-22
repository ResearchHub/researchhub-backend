from django.db import models

from utils.models import DefaultModel


class ResearchJourney(DefaultModel):
    created_by = models.ForeignKey(
        "user.User",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_research_journeys",
        help_text="User who created the source preregistration.",
    )
    grant = models.ForeignKey(
        "purchase.Grant",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="research_journeys",
        help_text="Grant that funded this journey, when known.",
    )
    preregistration_post = models.ForeignKey(
        "researchhub_document.ResearchhubPost",
        blank=True,
        db_index=False,
        null=True,
        on_delete=models.SET_NULL,
        related_name="research_journeys",
        help_text="Preregistration post that started this journey.",
    )
    is_in_journal = models.BooleanField(
        default=False,
        help_text="Whether this journey is included in the journal feed.",
    )
    journal_included_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When this journey entered the journal feed.",
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["is_in_journal", "-journal_included_date"],
                name="journey_journal_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["preregistration_post"],
                condition=models.Q(preregistration_post__isnull=False),
                name="unique_journey_prereg_post",
            ),
        ]

    def __str__(self):
        if self.id is None:
            return "Unsaved Research Journey"
        return f"Research Journey {self.id}"
