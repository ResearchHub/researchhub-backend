from django.core.validators import MinValueValidator
from django.db import models

from utils.models import DefaultModel


class PreregistrationSettings(DefaultModel):
    """Unpublished preregistration Details for a notebook draft."""

    note = models.OneToOneField(
        "note.Note",
        on_delete=models.CASCADE,
        related_name="preregistration_settings",
    )
    goal_amount = models.DecimalField(
        blank=True,
        decimal_places=2,
        max_digits=19,
        null=True,
    )
    goal_currency = models.CharField(
        blank=True,
        max_length=16,
        null=True,
    )
    duration_days = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1)],
    )
    is_public = models.BooleanField(
        blank=True,
        null=True,
    )
    nonprofit = models.ForeignKey(
        "organizations.NonprofitOrg",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="note_preregistration_settings",
    )

    class Meta:
        db_table = "note_preregistration_settings"
