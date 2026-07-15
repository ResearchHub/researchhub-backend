from django.db import models

from research_ai.constants import EmailTemplateType
from research_ai.models.expert_search import ExpertSearch
from utils.models import DefaultModel


class GeneratedEmail(DefaultModel):
    """
    Stores generated outreach emails for experts.
    """

    class Status(models.TextChoices):
        BOUNCED = "bounced", "bounced"
        COMPLAINED = "complained", "complained"
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
    proposal_draft = models.ForeignKey(
        "research_ai.ProposalDraft",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_emails",
        db_comment="Expert-specific proposal draft referenced by this outreach email.",
    )
    note_invitation = models.ForeignKey(
        "invite.NoteInvitation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_emails",
        db_comment="Invitation link embedded in proposal-draft outreach.",
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
        db_comment=(
            "LLM prompt key; null when placeholder is for fixed {{}} template only."
        ),
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
    complained_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="Timestamp of complaint (spam report) email event.",
    )

    class Meta:
        db_table = "research_ai_generated_email"
        ordering = ["-created_date"]
        indexes = [
            models.Index(fields=["created_by"], name="research_ai_ge_created_by"),
        ]

    def __str__(self):
        return f"GeneratedEmail {self.id} ({self.expert_name})"
