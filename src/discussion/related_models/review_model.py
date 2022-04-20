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
