from django.db import models
from django.utils import timezone

from utils.models import DefaultModel


class UnifiedDocumentShareLink(DefaultModel):
    """Anonymous, expiring read access to a single unified document.

    The token is the sole credential, so it is stored in plaintext to let an
    eligible user retrieve and re-share the link they already handed out.
    Regenerating an expired link rotates the token, which permanently kills
    the previous URL rather than resurrecting it.
    """

    unified_document = models.OneToOneField(
        "researchhub_document.ResearchhubUnifiedDocument",
        on_delete=models.CASCADE,
        related_name="share_link",
    )
    created_by = models.ForeignKey(
        "user.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_share_links",
        help_text="Who last generated the link. Audit only, grants no privileges.",
    )
    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def __str__(self) -> str:
        return f"Share link for unified document {self.unified_document_id}"
