from django.db import models

from utils.models import DefaultModel


class CoverImageGeneration(DefaultModel):
    """One request for AI-generated cover image options for a proposal or RFP.

    The banners are generated in a worker and stored under ``image_keys``; the
    user picks one in the publishing form, which then sends its key as the
    post's ``image`` like an uploaded cover.
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
    image_keys = models.JSONField(
        default=list,
        blank=True,
        db_comment="Storage keys of the generated banners, in display order.",
    )
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["created_by", "created_date"],
                name="ra_cig_user_created_idx",
            ),
        ]
