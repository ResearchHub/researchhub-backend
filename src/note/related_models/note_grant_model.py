from django.db import models

from purchase.related_models.grant_model import Grant
from utils.models import DefaultModel


class NoteGrant(DefaultModel):
    """Unpublished grant Details for a notebook draft."""

    note = models.OneToOneField(
        "note.Note",
        on_delete=models.CASCADE,
        related_name="grant_details",
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
        null=True,
    )
    organization = models.CharField(
        blank=True,
        max_length=255,
        null=True,
    )
    description = models.TextField(
        blank=True,
        null=True,
    )
    end_date = models.DateTimeField(
        blank=True,
        null=True,
    )
    application_visibility = models.CharField(
        blank=True,
        choices=Grant.APPLICATION_VISIBILITY_CHOICES,
        max_length=16,
        null=True,
    )
    contacts = models.ManyToManyField(
        "user.User",
        blank=True,
        related_name="note_grant_contacts",
    )
