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
            # Index for supporting the retrieval of the latest version of a paper in
            # the ResearchHub journal
            Index(
                fields=["base_doi", "-created_date"],
                name="paper_ver_rh_doi_created_idx",
                condition=models.Q(
                    base_doi__isnull=False,
                    journal="RESEARCHHUB",
                ),
            ),
        )


# A series of papers, representing all versions of a paper
class PaperSeries(DefaultModel):
    pass
