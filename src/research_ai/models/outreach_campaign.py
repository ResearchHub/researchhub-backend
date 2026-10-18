from django.contrib.postgres.fields import ArrayField
from django.db import models

from research_ai.models.email_template import EmailTemplate
from utils.models import DefaultModel


class OutreachCampaign(DefaultModel):
    """
    Per-editor outreach campaign published from a shared EmailTemplate.
    Unique on (editor, template); republish updates the same provider campaign.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        NO_ACTIVE_MAILBOXES = "no_active_mailboxes", "No active mailboxes"
        ERROR = "error", "Error"

    editor = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="outreach_campaigns",
        db_comment="Editor who published this campaign.",
    )
    template = models.ForeignKey(
        EmailTemplate,
        on_delete=models.PROTECT,
        related_name="outreach_campaigns",
        db_comment=(
            "Shared EmailTemplate this campaign was published from. "
            "PROTECT keeps the local external_campaign_id mapping if the "
            "template is deleted while campaigns still exist."
        ),
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        db_comment="Editor-chosen campaign name shown in RH and the outreach provider.",
    )
    external_campaign_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        db_comment="Provider campaign id for this published outreach campaign.",
    )
    published_subject = models.TextField(
        blank=True,
        db_comment="Subject snapshot at last successful publish.",
    )
    published_body = models.TextField(
        blank=True,
        db_comment="Body snapshot at last successful publish.",
    )
    published_variable_keys = ArrayField(
        models.CharField(max_length=128),
        default=list,
        blank=True,
        db_comment=(
            "Flattened provider custom_variable keys published with this "
            "campaign (e.g. expert_name)."
        ),
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="Timestamp of the last successful publish.",
    )

    class Meta:
        db_table = "research_ai_outreach_campaign"
        ordering = ["-updated_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["editor", "template"],
                name="ra_oc_editor_template_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["editor", "status"],
                name="ra_oc_editor_status",
            ),
        ]

    def __str__(self):
        label = (self.name or "").strip() or f"id={self.id}"
        return f"OutreachCampaign {label} (editor={self.editor_id})"
