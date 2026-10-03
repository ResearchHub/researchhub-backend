from datetime import timedelta

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from encrypted_fields import EncryptedTextField

from utils.models import DefaultModel

# Personal Gmail only; Workspace / ResearchHub domains are rejected at connect time.
GMAIL_OUTREACH_ALLOWED_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def normalize_outreach_mailbox_email(email: str) -> str:
    """Normalize mailbox email for storage and allowlist checks."""
    return (email or "").strip().lower()


def is_allowed_outreach_mailbox_email(email: str) -> bool:
    """Return True if email is a personal @gmail.com / @googlemail.com address."""
    normalized = normalize_outreach_mailbox_email(email)
    if "@" not in normalized:
        return False
    domain = normalized.rsplit("@", 1)[-1]
    return domain in GMAIL_OUTREACH_ALLOWED_DOMAINS


class OutreachMailboxConnection(DefaultModel):
    """
    Editor's connected personal Gmail for Expert Finder outreach.

    OAuth tokens are encrypted at rest. Do not reuse allauth login SocialToken;
    outreach consent is a separate Connect Gmail flow with gmail.send/readonly.
    """

    class Provider(models.TextChoices):
        GMAIL = "gmail", "Gmail"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        NEEDS_REAUTH = "needs_reauth", "Needs reauth"
        REVOKED = "revoked", "Revoked"

    user = models.OneToOneField(
        "user.User",
        on_delete=models.CASCADE,
        related_name="outreach_mailbox_connection",
        db_comment="One active outreach mailbox per editor.",
    )
    provider = models.CharField(
        max_length=16,
        choices=Provider.choices,
        default=Provider.GMAIL,
        db_comment="Mailbox provider; only gmail in v1.",
    )
    email = models.EmailField(
        db_comment="Normalized personal Gmail address used as From.",
    )
    refresh_token = EncryptedTextField(
        blank=True,
        help_text="Encrypted OAuth refresh token.",
    )
    access_token = EncryptedTextField(
        blank=True,
        help_text="Encrypted OAuth access token.",
    )
    access_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="When the access token expires.",
    )
    scopes = ArrayField(
        models.CharField(max_length=128),
        default=list,
        blank=True,
        db_comment="OAuth scopes granted for this connection.",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
        db_comment="active / needs_reauth / revoked.",
    )
    last_error = models.TextField(
        blank=True,
        db_comment="Last auth or send error message, if any.",
    )
    connected_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="When the mailbox was last successfully connected.",
    )

    class Meta:
        db_table = "research_ai_outreach_mailbox_connection"

    def __str__(self):
        return f"OutreachMailboxConnection {self.id} ({self.email})"

    def clean(self):
        super().clean()
        self.email = normalize_outreach_mailbox_email(self.email)
        if self.email and not is_allowed_outreach_mailbox_email(self.email):
            raise ValidationError(
                {
                    "email": (
                        "Only personal @gmail.com / @googlemail.com mailboxes "
                        "are allowed for outreach."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.email = normalize_outreach_mailbox_email(self.email)
        super().save(*args, **kwargs)

    def is_access_token_expired(self, buffer_seconds: int = 60) -> bool:
        """Return True if access token is missing, expired, or expiring soon."""
        if not self.access_token_expires_at:
            return True
        return timezone.now() >= self.access_token_expires_at - timedelta(
            seconds=buffer_seconds
        )
