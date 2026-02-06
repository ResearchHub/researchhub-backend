import uuid

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

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
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
        help_text="Document-based search; null for custom query.",
    )
    query = models.TextField(
        help_text="Research description or document content used for the search.",
    )
    input_type = models.CharField(
        max_length=32,
        choices=[
            ("abstract", "abstract"),
            ("pdf", "pdf"),
            ("custom_query", "custom_query"),
            ("full_content", "full_content"),
        ],
        default="abstract",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Expert count, expertise_level, region, state, gender, etc.",
    )
    excluded_expert_names = models.JSONField(
        default=list,
        blank=True,
        help_text="Expert full names to exclude (multiple runs on same doc).",
    )
    llm_model = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=32,
        choices=[
            ("pending", "pending"),
            ("processing", "processing"),
            ("completed", "completed"),
            ("failed", "failed"),
        ],
        default="pending",
        db_index=True,
    )
    progress = models.IntegerField(default=0)  # 0-100
    current_step = models.CharField(max_length=512, blank=True)
    expert_results = models.JSONField(
        default=list,
        blank=True,
        help_text="Expert dicts: name, title, affiliation, expertise, email, notes, sources.",
    )
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


class GeneratedEmail(DefaultModel):
    """
    Stores generated outreach emails for experts.
    """

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="created_research_ai_generated_emails",
    )
    expert_search = models.ForeignKey(
        ExpertSearch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_emails",
    )
    expert_name = models.CharField(max_length=255, blank=True)
    expert_title = models.CharField(max_length=255, blank=True)
    expert_affiliation = models.CharField(max_length=512, blank=True)
    expert_email = models.CharField(max_length=255, blank=True)
    expertise = models.CharField(max_length=512, blank=True)
    email_subject = models.TextField(blank=True)
    email_body = models.TextField(blank=True)
    template = models.CharField(
        max_length=32,
        choices=[
            ("collaboration", "collaboration"),
            ("consultation", "consultation"),
            ("conference", "conference"),
            ("peer-review", "peer-review"),
            ("publication", "publication"),
            ("rfp-outreach", "rfp-outreach"),
            ("custom", "custom"),
        ],
        default="custom",
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("draft", "draft"),
            ("sent", "sent"),
        ],
        default="draft",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "research_ai_generated_email"
        ordering = ["-created_date"]
        indexes = [
            models.Index(fields=["created_by"], name="research_ai_ge_created_by"),
        ]

    def __str__(self):
        return f"GeneratedEmail {self.id} ({self.expert_name})"
