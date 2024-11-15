from django.db import models

from utils.models import DefaultModel


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
