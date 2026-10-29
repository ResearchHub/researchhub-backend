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
    note = models.ForeignKey(
        "note.Note",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="The draft the covers are for; its cover logo is placed in them.",
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    title = models.TextField()
    subtitle = models.TextField(blank=True, default="")
    organization = models.CharField(max_length=200, blank=True, default="")
    funding_amount_usd = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    logo_file = models.ForeignKey(
        "research_ai.AgentFile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="The chat attachment placed in the banners as the logo, if any.",
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


class NoteCoverLogo(DefaultModel):
    """The image attached in a note's chat that its generated covers use as the
    organization's logo, as the chat agent recorded when the user said so."""

    note = models.OneToOneField(
        "note.Note", on_delete=models.CASCADE, related_name="cover_logo"
    )
    file = models.ForeignKey(
        "research_ai.AgentFile",
        on_delete=models.CASCADE,
        related_name="cover_logo_notes",
    )
    set_by = models.ForeignKey(
        "user.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
