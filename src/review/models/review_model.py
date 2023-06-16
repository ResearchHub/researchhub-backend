from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
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
    content_type = models.ForeignKey(
        ContentType, null=True, blank=False, on_delete=models.SET_NULL
    )
    object_id = models.PositiveIntegerField(
        null=True,
        blank=False,
    )
    item = GenericForeignKey(
        "content_type",
        "object_id",
    )
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        related_name="reviews",
        blank=False,
        null=True,
        on_delete=models.SET_NULL,
    )
