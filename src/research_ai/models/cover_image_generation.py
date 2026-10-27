from django.db import models

from utils.models import DefaultModel


class CoverImageGeneration(DefaultModel):
    """One request for an AI-generated cover image for a proposal or RFP.

    The banner is generated in a worker and stored under ``image_key``; the
    publishing form shows it and sends its key as the post's ``image``, like an
    uploaded cover.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    class DocumentType(models.TextChoices):
        PREREGISTRATION = "PREREGISTRATION"
        GRANT = "GRANT"

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="cover_image_generations",
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    title = models.TextField()
    subtitle = models.TextField(blank=True, default="")
    organization = models.CharField(max_length=200, blank=True, default="")
    funding_amount_usd = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    image_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="Storage key of the generated banner.",
    )
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["created_by", "created_date"],
                name="ra_cig_user_created_idx",
            ),
        ]
