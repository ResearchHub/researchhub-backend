from django.db import models
from django.db.models import Q

from utils.models import DefaultModel


class ResearcherProfile(DefaultModel):
    """
    Source-attributed researcher profile built by the researcher-profile agent.

    One row per researcher, keyed on the ResearchHub ``user`` (the assistant's
    lookup) and/or the outreach ``expert`` (proposal drafts for people who have
    not signed up). A row built for an expert is attached to the user once they
    sign up, so the build is reused rather than repeated.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        BUILDING = "BUILDING", "Building"
        READY = "READY", "Ready"
        UNRESOLVED = "UNRESOLVED", "Unresolved"
        FAILED = "FAILED", "Failed"

    user = models.OneToOneField(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="researcher_profile",
        db_comment="ResearchHub user this profile describes.",
    )
    expert = models.OneToOneField(
        "research_ai.Expert",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="researcher_profile",
        db_comment="Outreach expert this profile describes.",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    schema_version = models.PositiveSmallIntegerField(
        default=0,
        db_comment="Agent output schema version of ``data``; 0 until first built.",
    )
    openalex_author_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        db_comment="Resolved OpenAlex author id; blank when unresolved.",
    )
    orcid = models.CharField(max_length=255, blank=True)
    confidence = models.FloatField(
        null=True,
        blank=True,
        db_comment="Agent's 0..1 confidence in the OpenAlex resolution.",
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        db_comment=(
            "Agent output: schema_version, built_at, resolution, works, "
            "capabilities, errors. Kept while a rebuild runs."
        ),
    )
    inputs_hash = models.CharField(
        max_length=64,
        blank=True,
        db_comment=(
            "Hash of the seed the last build ran on; a different seed triggers "
            "a rebuild. Blank when unknown (rows copied from Expert.profile)."
        ),
    )
    built_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(
        default=0,
        db_comment="Consecutive failed builds; reset by a successful build.",
    )
    last_error = models.TextField(blank=True)
    next_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="Earliest retry after a failed or deferred build.",
    )
    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="While BUILDING: when an unfinished build's claim lapses.",
    )

    class Meta:
        db_table = "research_ai_researcher_profile"
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False) | Q(expert__isnull=False),
                name="ra_researcher_profile_has_subject",
            ),
        ]

    def __str__(self):
        return f"ResearcherProfile {self.id} ({self.status})"

    @property
    def has_data(self) -> bool:
        return isinstance(self.data, dict) and bool(self.data)
