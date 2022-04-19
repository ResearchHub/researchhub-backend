from django.db import models
from utils.models import DefaultModel

class Review(DefaultModel):
    score = models.FloatField(
        default=None,
        null=True,
        blank=False
    )