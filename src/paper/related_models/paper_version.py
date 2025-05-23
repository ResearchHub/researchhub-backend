from django.db import models
from django.db.models import Func, Index

from utils.models import DefaultModel


class PaperVersion(models.Model):
    PREPRINT = "PREPRINT"
    PUBLISHED = "PUBLISHED"
    PUBLICATION_STATUS_CHOICES = [
        (PREPRINT, "Preprint"),
        (PUBLISHED, "Published"),
    ]

    # Journal choices
    RESEARCHHUB = "RESEARCHHUB"
    JOURNAL_CHOICES = [
        (RESEARCHHUB, "ResearchHub Journal"),
    ]

    paper = models.OneToOneField(
        "Paper", on_delete=models.CASCADE, related_name="version"
    )
    version = models.IntegerField(default=1)
    base_doi = models.CharField(max_length=255, default=None, null=True, blank=True)
    original_paper = models.ForeignKey(
        "Paper", related_name="original_paper", null=True, on_delete=models.SET_NULL
    )
    message = models.TextField(default=None, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    journal = models.TextField(
        choices=JOURNAL_CHOICES,
        null=True,
        blank=True,
        help_text="The journal this paper version belongs to",
    )
    publication_status = models.TextField(
        choices=PUBLICATION_STATUS_CHOICES,
        default=PREPRINT,
        help_text="Indicates whether this is a preprint or a published article",
    )

    class Meta:
        indexes = (
            Index(
                Func("base_doi", function="UPPER"),
                name="paper_version_doi_upper_idx",
            ),
        )


# A series of papers, representing all versions of a paper
class PaperSeries(DefaultModel):
    pass


class PaperSeriesDeclaration(DefaultModel):
    ACCEPT_TERMS_AND_CONDITIONS = "ACCEPT_TERMS_AND_CONDITIONS"
    AUTHORIZE_CC_BY_4_0 = "AUTHORIZE_CC_BY_4_0"
    CONFIRM_AUTHORS_RIGHTS = "CONFIRM_AUTHORS_RIGHTS"
    CONFIRM_ORIGINALITY_AND_COMPLIANCE = "CONFIRM_ORIGINALITY_AND_COMPLIANCE"

    DECLARATION_TYPE_CHOICES = [
        (ACCEPT_TERMS_AND_CONDITIONS, "Accept Terms and Conditions"),
        (AUTHORIZE_CC_BY_4_0, "Authorize CC BY 4.0"),
        (CONFIRM_AUTHORS_RIGHTS, "Confirm Authors Rights"),
        (CONFIRM_ORIGINALITY_AND_COMPLIANCE, "Confirm Originality and Compliance"),
    ]

    paper_series = models.ForeignKey(
        "PaperSeries", on_delete=models.CASCADE, related_name="declarations"
    )
    declaration_type = models.CharField(
        max_length=100,
        choices=DECLARATION_TYPE_CHOICES,
    )
    accepted = models.BooleanField(
        default=False, help_text="Indicates if the declaration has been accepted"
    )
    accepted_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        null=True,
        related_name="paper_series_declarations",
        help_text="User who accepted this declaration",
    )
    accepted_date = models.DateTimeField(
        null=True, blank=True, help_text="When the declaration was accepted"
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["paper_series", "declaration_type", "accepted_by"]
        indexes = [
            models.Index(fields=["paper_series", "declaration_type", "accepted_by"]),
        ]
