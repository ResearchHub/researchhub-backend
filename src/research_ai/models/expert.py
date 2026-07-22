from django.db import models
from django.db.models.functions import Lower

from utils.models import DefaultModel
from utils.openalex import orcid_from_urls


class Expert(DefaultModel):
    """
    Canonical expert contact keyed by professional email (one row per email).
    """

    email = models.EmailField(
        max_length=254,
        db_index=True,
        db_comment="Normalized lowercase for matching.",
    )
    honorific = models.CharField(
        max_length=64,
        blank=True,
        db_comment="e.g. Dr, Prof, Mr, Ms",
    )
    first_name = models.CharField(max_length=255, blank=True)
    middle_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    name_suffix = models.CharField(
        max_length=64,
        blank=True,
        db_comment="Credentials e.g. PhD, MD",
    )
    academic_title = models.CharField(
        max_length=255,
        blank=True,
        db_comment="Role e.g. Professor, Associate Professor",
    )
    affiliation = models.TextField(blank=True)
    expertise = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    sources = models.JSONField(default=list, blank=True)
    profile = models.JSONField(
        default=dict,
        blank=True,
        db_comment=(
            "Persisted, source-attributed researcher profile built once by "
            "researcher_profile_service (OpenAlex/ORCID resolver + web search) and "
            "reused by the proposal draft engine and source verifier."
        ),
    )
    is_manually_added = models.BooleanField(
        default=False,
        db_comment=(
            "True if this expert has ever been manually added to a search by a "
            "user. Used to prioritize manual entries in search result listings."
        ),
    )
    registered_user = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="research_ai_expert_profiles",
        db_comment="RH user who signed up with this expert email.",
    )
    last_email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment=(
            "Last time an outreach email was sent to this expert address (any search)."
        ),
    )

    class Meta:
        db_table = "research_ai_expert"
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="research_ai_expert_email_lower_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["registered_user"],
                name="ra_expert_reg_user_idx",
            ),
        ]

    def __str__(self):
        return f"Expert {self.id} ({self.email})"

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(str(p).strip() for p in parts if p and str(p).strip()).strip()

    @property
    def source_urls(self) -> list[str]:
        urls: list[str] = []
        for item in self.sources or []:
            if isinstance(item, dict):
                url = str(item.get("url") or "").strip()
            elif isinstance(item, str):
                url = item.strip()
            else:
                url = ""
            if url:
                urls.append(url)
        return urls

    @property
    def orcid(self) -> str | None:
        """ORCID mined from the ``sources`` URLs, or ``None`` when absent."""
        return orcid_from_urls(self.source_urls)

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)
