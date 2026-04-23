from django.db import models
from django.db.models.functions import Lower

from research_ai.constants import EmailTemplateType
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
        db_comment="Optional user-defined search name; auto-filled from document title if not provided.",
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
    excluded_expert_names = models.JSONField(
        default=list,
        blank=True,
        db_comment="Expert full names to exclude (multiple runs on same doc).",
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
    expert_results = models.JSONField(
        default=list,
        blank=True,
        db_comment="Expert dicts: name, title, affiliation, expertise, email, notes, sources.",
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
        db_comment="Last time an outreach email was sent to this expert address (any search).",
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

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)


class SearchExpert(DefaultModel):
    """
    Membership of an Expert in one ExpertSearch (at most once per search).
    """

    expert_search = models.ForeignKey(
        ExpertSearch,
        on_delete=models.CASCADE,
        related_name="search_experts",
    )
    expert = models.ForeignKey(
        Expert,
        on_delete=models.CASCADE,
        related_name="search_experts",
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "research_ai_search_expert"
        ordering = ["expert_search", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["expert_search", "expert"],
                name="research_ai_se_search_expert_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["expert_search", "position"],
                name="ra_se_search_pos_idx",
            ),
        ]

    def __str__(self):
        return f"SearchExpert search={self.expert_search_id} expert={self.expert_id}"


class GeneratedEmail(DefaultModel):
    """
    Stores generated outreach emails for experts.
    """

    class Status(models.TextChoices):
        BOUNCED = "bounced", "bounced"
        DRAFT = "draft", "draft"
        SENT = "sent", "sent"
        PROCESSING = "processing", "processing"
        FAILED = "failed", "failed"
        SENDING = "sending", "sending"
        SEND_FAILED = "send_failed", "send_failed"
        CLOSED = "closed", "closed"

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
    expert_email = models.EmailField(blank=True)
    expertise = models.CharField(max_length=512, blank=True)
    email_subject = models.TextField(blank=True)
    email_body = models.TextField(blank=True)
    template = models.CharField(
        max_length=32,
        choices=EmailTemplateType.choices,
        default=EmailTemplateType.CUSTOM,
        null=True,
        blank=True,
        db_comment="LLM prompt key; null when placeholder is for fixed {{}} template only.",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    notes = models.TextField(blank=True)
    ses_message_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        db_comment="SES message ID to correlate email events.",
    )
    opened_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="Timestamp of first tracked email open event.",
    )
    open_count = models.IntegerField(
        default=0,
        db_comment="Number of email open events.",
    )
    bounced_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="Timestamp of bounce email event.",
    )

    class Meta:
        db_table = "research_ai_generated_email"
        ordering = ["-created_date"]
        indexes = [
            models.Index(fields=["created_by"], name="research_ai_ge_created_by"),
        ]

    def __str__(self):
        return f"GeneratedEmail {self.id} ({self.expert_name})"


class DocumentInvitedExpert(DefaultModel):
    """
    Materialized "invited" experts per unified document.
    """

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        related_name="document_invited_experts",
    )
    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="document_invited_expert_records",
    )
    expert_search = models.ForeignKey(
        ExpertSearch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_invited_experts",
        db_comment="Search that surfaced this expert for this document.",
    )
    generated_email = models.ForeignKey(
        GeneratedEmail,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_invited_experts",
        db_comment="Generated email if invite tied to one; null if only in expert_results.",
    )

    class Meta:
        db_table = "research_ai_document_invited_expert"
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["unified_document", "user"],
                name="research_ai_die_doc_user_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["unified_document"],
                name="research_ai_die_unified_doc",
            ),
            models.Index(
                fields=["expert_search"],
                name="research_ai_die_expert_search",
            ),
        ]

    def __str__(self):
        return (
            f"DocumentInvitedExpert doc={self.unified_document_id} user={self.user_id}"
        )


class EmailTemplate(DefaultModel):
    """
    User-defined variable template for outreach emails ({{entity.field}} placeholders).
    """

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="created_research_ai_email_templates",
    )
    name = models.CharField(
        max_length=255,
        db_comment="User-defined template name.",
    )
    email_subject = models.TextField(
        blank=True,
        db_comment="Subject; may contain {{entity.field}}.",
    )
    email_body = models.TextField(
        blank=True,
        db_comment="Body; may contain {{entity.field}}.",
    )

    class Meta:
        db_table = "research_ai_email_template"
        ordering = ["-updated_date"]
        indexes = [
            models.Index(
                fields=["created_by"],
                name="research_ai_et_created_by",
            ),
        ]

    def __str__(self):
        return f"EmailTemplate {self.id} ({self.name})"
