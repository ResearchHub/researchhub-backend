from django.db import models
from django.utils.translation import gettext_lazy as _

from user.related_models.user_model import User
from utils.models import DefaultModel


class PhoneVerification(DefaultModel):
    """
    Model to store phone verification codes and their status for users.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        VERIFIED = "VERIFIED", _("Verified")
        EXPIRED = "EXPIRED", _("Expired")

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="phone_verification",
    )
    phone_number = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempts = models.IntegerField(default=0)
    send_count = models.IntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=models.Q(status="VERIFIED"),
                name="unique_verified_phone_number",
            )
        ]
