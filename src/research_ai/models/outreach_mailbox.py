from django.db import models
from django.db.models.functions import Lower

from utils.models import DefaultModel, SoftDeletableModel


class OutreachMailbox(DefaultModel, SoftDeletableModel):
    """
    Editor-owned email account connected for outreach sending.

    May be personal Gmail (app password / IMAP-SMTP) or a Google Workspace
    account connected via provider OAuth. Credentials and OAuth tokens are
    stored by the outreach provider and never persisted here.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISCONNECTING = "disconnecting", "Disconnecting"
        ERROR = "error", "Error"
        DISCONNECTED = "disconnected", "Disconnected"

    editor = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="outreach_mailboxes",
        db_comment="ResearchHub editor who connected this outreach account.",
    )
    email = models.EmailField(
        max_length=254,
        db_index=True,
        db_comment="Normalized lowercase email; outreach provider account key.",
    )
    provider_code = models.PositiveSmallIntegerField(
        default=1,
        db_comment=(
            "Outreach provider account type code. 1 = custom IMAP/SMTP "
            "(personal Gmail app password); other values are OAuth Google "
            "Workspace codes as returned by the provider accounts API."
        ),
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="Local mailbox lifecycle; maps from provider account status.",
    )
    daily_limit = models.PositiveIntegerField(
        default=10,
        db_comment="Cached daily send limit for this account.",
    )
    reply_to = models.EmailField(
        blank=True,
        default="",
        db_comment="Cached custom Reply-To address synced to the outreach provider.",
    )

    class Meta:
        db_table = "research_ai_outreach_mailbox"
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="ra_om_email_lower_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["editor", "status"],
                name="ra_om_editor_status",
            ),
        ]

    def __str__(self):
        return f"OutreachMailbox {self.id} ({self.email})"

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        if self.reply_to:
            self.reply_to = self.reply_to.strip().lower()
        super().save(*args, **kwargs)
