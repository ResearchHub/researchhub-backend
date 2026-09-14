from django.db import models

from utils.models import DefaultModel


class ResearchJourney(DefaultModel):
    grant_post = models.ForeignKey(
        "researchhub_document.ResearchhubPost",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="grant_research_journeys",
        help_text="Grant post that funded this journey, when known.",
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

    class Meta:
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
