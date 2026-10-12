from django.db import models

from utils.models import DefaultModel, SoftDeletableModel


class OutreachMailbox(DefaultModel, SoftDeletableModel):
    """
    Editor-owned Gmail account connected for outreach sending.
    The Google app password is sent to the outreach provider and never persisted here.
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
        db_comment="ResearchHub editor who connected this Gmail account.",
    )
    email = models.EmailField(
        unique=True,
        db_comment="Normalized Gmail address; provider account key.",
    )
    provider_code = models.PositiveSmallIntegerField(
        default=1,
        db_comment=(
            "Outreach provider account type. 1 = custom IMAP/SMTP "
            "(personal Gmail with app password)."
        ),
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="Local mailbox lifecycle; maps from provider account status.",
    )
    daily_limit = models.PositiveIntegerField(
        default=30,
        db_comment="Cached daily send limit for this account.",
    )

    class Meta:
        db_table = "research_ai_outreach_mailbox"
        ordering = ["-created_date"]
        indexes = [
            models.Index(
                fields=["editor", "status"],
                name="ra_om_editor_status",
            ),
        ]

    def __str__(self):
        return f"OutreachMailbox {self.id} ({self.email})"
