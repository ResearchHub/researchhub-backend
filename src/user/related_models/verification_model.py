from django.db import models

from user.models import Author, User
from utils.models import DefaultModel


class Verification(DefaultModel):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    INITIATED = "INITIATED"

    VERIFICATION_CHOICES = [
        (APPROVED, APPROVED),
        (DENIED, DENIED),
        (INITIATED, INITIATED),
    ]

    user = models.ForeignKey(
        User,
        related_name="verification",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    details = models.TextField(null=True, blank=True)
    related_author = models.ForeignKey(
        Author,
        null=True,
        blank=True,
        related_name="verification",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        choices=VERIFICATION_CHOICES,
        default=INITIATED,
        max_length=16,
        null=False,
        blank=True,
    )


class VerificationFile(DefaultModel):
    verification = models.ForeignKey(
        Verification, related_name="files", on_delete=models.CASCADE
    )
    file = models.FileField(
        upload_to="uploads/verification/%Y/%m/%d",
    )
