from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from utils.models import DefaultModel, SoftDeletableModel


class Review(SoftDeletableModel, DefaultModel):
    score = models.FloatField(
        null=True,
        blank=False,
        default=1,
        validators=[MaxValueValidator(10), MinValueValidator(1)],
    )
    created_by = models.ForeignKey(
        "user.User",
        related_name="reviews",
        blank=False,
        null=True,
        on_delete=models.SET_NULL,
    )
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        related_name="reviews",
        blank=False,
        null=True,
        on_delete=models.SET_NULL,
    )
