from django.db import models
from django.db.models import Q

from ai_peer_review.constants import ExpertDimensionScore, OverallRating, ReviewStatus
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultModel


class ProposalReview(DefaultModel):
    """
    AI 5-dimension review for a proposal
    """

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_proposal_reviews",
    )
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        related_name="proposal_reviews",
        db_comment="Proposal unified document.",
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
        db_table = "ai_peer_review_proposalreview"
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["unified_document", "grant"],
                condition=Q(grant__isnull=False),
                name="ai_peer_review_pr_ud_grant_nn",
            ),
            models.UniqueConstraint(
                fields=["unified_document"],
                condition=Q(grant__isnull=True),
                name="ai_peer_review_pr_ud_standalone",
            ),
        ]
        indexes = [
            models.Index(
                fields=["grant", "status"],
                name="ai_peer_review_pr_grant_status",
            ),
        ]

    def __str__(self):
        return f"ProposalReview {self.id} ({self.status})"


class RFPSummary(DefaultModel):
    """
    RFP brief (~500 words) and comparison across proposals.
    """

    grant = models.OneToOneField(
        "purchase.Grant",
        on_delete=models.CASCADE,
        related_name="ai_peer_review_rfp_summary",
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
        db_comment="Funder-facing comparison across proposals.",
    )
    executive_comparison_updated_date = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    llm_model = models.CharField(max_length=256, blank=True)
    processing_time = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "ai_peer_review_rfp_summary"
        ordering = ["-updated_date"]

    def __str__(self):
        return f"RFPSummary grant={self.grant_id} ({self.status})"


class ReportEntitlement(DefaultModel):
    """
    User may view an AI proposal report.
    """

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="ai_peer_review_report_entitlements",
    )
    proposal_review = models.ForeignKey(
        ProposalReview,
        on_delete=models.CASCADE,
        related_name="report_entitlements",
    )
    purchase = models.ForeignKey(
        "purchase.Purchase",
        on_delete=models.CASCADE,
        related_name="ai_peer_review_report_entitlements",
    )

    class Meta:
        db_table = "ai_peer_review_report_entitlement"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "proposal_review"],
                name="ai_peer_review_report_ent_user_pr",
            ),
        ]

    def __str__(self):
        return f"ReportEntitlement user={self.user_id} pr={self.proposal_review_id}"


class EditorialFeedback(DefaultModel):
    """
    One human editorial assessment per proposal.
    Any editor or moderator may create or update.
    """

    unified_document = models.OneToOneField(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        related_name="ai_peer_review_editorial_feedback",
        db_comment="At most one editorial feedback row per unified document.",
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_peer_review_editorial_feedbacks_created",
        db_comment="Editor who first created this feedback row.",
    )
    updated_by = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_peer_review_editorial_feedbacks_updated",
        db_comment="Editor who last saved changes.",
    )
    fundability_expert = models.CharField(
        max_length=16,
        choices=ExpertDimensionScore.choices,
    )
    feasibility_expert = models.CharField(
        max_length=16,
        choices=ExpertDimensionScore.choices,
    )
    novelty_expert = models.CharField(
        max_length=16,
        choices=ExpertDimensionScore.choices,
    )
    impact_expert = models.CharField(
        max_length=16,
        choices=ExpertDimensionScore.choices,
    )
    reproducibility_expert = models.CharField(
        max_length=16,
        choices=ExpertDimensionScore.choices,
    )
    expert_insights = models.TextField(blank=True)

    class Meta:
        db_table = "ai_peer_review_editorial_feedback"

    def __str__(self):
        return f"EditorialFeedback ud={self.unified_document_id}"
