from django.db import models
from user.models import Author


class Paper(models.Model):
    title = models.CharField(max_length=255)
    authors = models.ManyToManyField(
        Author,
        related_name='authored_papers',
        blank=True
    )
