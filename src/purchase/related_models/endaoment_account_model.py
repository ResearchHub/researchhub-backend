from datetime import timedelta

from django.db import models
from django.utils import timezone

from utils.models import DefaultModel


class EndaomentAccount(DefaultModel):
    """
    Links a ResearchHub user to their Endaoment account.

    Stores OAuth tokens for authenticated API access to Endaoment DAF operations.
    """

    user = models.OneToOneField(
        "user.User",
        on_delete=models.CASCADE,
        related_name="endaoment_account",
    )

    access_token = models.TextField(help_text="Endaoment access token")
    refresh_token = models.TextField(
        null=True,
        blank=True,
        help_text="Endaoment refresh token",
    )
    token_expires_at = models.DateTimeField(help_text="Access token expiration time")

    endaoment_user_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Endaoment's user ID",
    )

    def is_token_expired(self, buffer_seconds: int = 60) -> bool:
        """
        Check if access token is expired or expiring soon, factoring in buffer_seconds.
        """
        return timezone.now() >= self.token_expires_at - timedelta(
            seconds=buffer_seconds
        )
