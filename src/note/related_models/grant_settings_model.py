from django.db import models

from purchase.related_models.grant_model import Grant
from utils.models import DefaultModel


class GrantSettings(DefaultModel):
    """Unpublished grant Details for a notebook draft."""

    note = models.OneToOneField(
        "note.Note",
        on_delete=models.CASCADE,
        related_name="grant_settings",
    )
    amount = models.DecimalField(
        blank=True,
        decimal_places=2,
        max_digits=19,
        null=True,
    )
    currency = models.CharField(
        blank=True,
        max_length=16,
    )
    organization = models.CharField(
        blank=True,
        max_length=255,
    )
    description = models.TextField(
        blank=True,
    )
    end_date = models.DateTimeField(
        blank=True,
        null=True,
    )
    application_visibility = models.CharField(
        blank=True,
        choices=Grant.APPLICATION_VISIBILITY_CHOICES,
        max_length=16,
    )
    contacts = models.ManyToManyField(
        "user.User",
        blank=True,
        related_name="note_grant_settings_contacts",
    )

    class Meta:
        db_table = "note_grant_settings"
