from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultModel


class ExpertSearch(DefaultModel):
    """
    Stores expert finder requests and results.
    Input is either a unified_document (abstract/pdf/post content) or custom query.
    """

    class InputType(models.TextChoices):
        ABSTRACT = "abstract", "abstract"
        PDF = "pdf", "pdf"
        CUSTOM_QUERY = "custom_query", "custom_query"
        FULL_CONTENT = "full_content", "full_content"

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        PROCESSING = "processing", "processing"
        COMPLETED = "completed", "completed"
        FAILED = "failed", "failed"

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="created_research_ai_expert_searches",
    )
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expert_searches",
        db_comment="Document-based search; null for custom query.",
    )
    name = models.CharField(
        max_length=512,
        blank=True,
        db_comment=(
            "Optional user-defined search name; auto-filled from document title if not "
            "provided."
        ),
    )
    query = models.TextField(
        db_comment="Research description or document content used for the search.",
    )
    input_type = models.CharField(
        max_length=32,
        choices=InputType.choices,
        default=InputType.ABSTRACT,
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Expert count, expertise_level, region, state, gender, etc.",
    )
    additional_context = models.TextField(
        blank=True,
        default="",
        db_comment=(
            "Optional user notes to steer expert-finder alongside the RFP/query."
        ),
    )
    llm_model = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    progress = models.IntegerField(default=0)  # 0-100
    current_step = models.CharField(max_length=512, blank=True)
    expert_count = models.IntegerField(default=0)
    report_pdf_url = models.URLField(max_length=2048, blank=True)
    report_csv_url = models.URLField(max_length=2048, blank=True)
    processing_time = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "research_ai_expert_search"
        ordering = ["-created_date"]
        indexes = [
            models.Index(
                fields=["created_by", "status"],
                name="research_ai_es_user_status",
            ),
            models.Index(fields=["status"], name="research_ai_es_status"),
        ]

    def __str__(self):
        return f"ExpertSearch {self.id} ({self.status})"
