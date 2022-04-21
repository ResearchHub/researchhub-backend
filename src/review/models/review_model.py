from django.db import models
from utils.models import DefaultModel
from django.core.validators import MaxValueValidator, MinValueValidator


class Review(DefaultModel):
    score = models.FloatField(
        null=True,
        blank=False,
        default=1,
        validators=[
            MaxValueValidator(10),
            MinValueValidator(1)
        ]
    )
    created_by = models.ForeignKey(
        'user.User',
        related_name='reviews',
        blank=False,
        null=True,
        on_delete=models.SET_NULL,
    )
