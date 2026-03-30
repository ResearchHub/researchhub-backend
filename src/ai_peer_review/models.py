from django.db import models
from django.db.models import Q

from ai_peer_review.constants import OverallRating, ReviewStatus
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultModel


class ProposalReview(DefaultModel):
    """
    AI 5-dimension review for a preregistration (proposal), optionally for a Grant (RFP).
    """

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="created_proposal_reviews",
    )
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        related_name="proposal_reviews",
        db_comment="Preregistration unified document.",
    )
    grant = models.ForeignKey(
        "purchase.Grant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="proposal_reviews",
        db_comment="Funding opportunity context; null for standalone review.",
    )
    status = models.CharField(
        max_length=32,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        db_index=True,
    )
    overall_rating = models.CharField(
        max_length=16,
        choices=OverallRating.choices,
        blank=True,
        null=True,
    )
    overall_score_numeric = models.IntegerField(null=True, blank=True)
    result_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    progress = models.IntegerField(default=0)
    current_step = models.CharField(max_length=512, blank=True)
    llm_model = models.CharField(max_length=256, blank=True)
    processing_time = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "research_ai_proposal_review"
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["unified_document", "grant"],
                condition=Q(grant__isnull=False),
                name="research_ai_pr_ud_grant_nn",
            ),
            models.UniqueConstraint(
                fields=["unified_document"],
                condition=Q(grant__isnull=True),
                name="research_ai_pr_ud_standalone",
            ),
        ]
        indexes = [
            models.Index(
                fields=["grant", "status"],
                name="research_ai_pr_grant_status",
            ),
        ]

    def __str__(self):
        return f"ProposalReview {self.id} ({self.status})"


class RFPSummary(DefaultModel):
    """
    RFP brief (~500 words) and optional funder executive comparison across proposals.
    """

    grant = models.OneToOneField(
        "purchase.Grant",
        on_delete=models.CASCADE,
        related_name="research_ai_rfp_summary",
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="created_rfp_summaries",
    )
    status = models.CharField(
        max_length=32,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        db_index=True,
    )
    summary_content = models.TextField(blank=True)
    executive_comparison_summary = models.TextField(
        blank=True,
        db_comment="Funder-facing comparison when top proposals are close.",
    )
    executive_comparison_updated_date = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    llm_model = models.CharField(max_length=256, blank=True)
    processing_time = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "research_ai_rfp_summary"
        ordering = ["-updated_date"]

    def __str__(self):
        return f"RFPSummary grant={self.grant_id} ({self.status})"
