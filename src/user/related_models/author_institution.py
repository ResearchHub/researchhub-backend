from django.contrib.postgres.fields import ArrayField
from django.db import models

from utils.models import DefaultModel


class AuthorInstitution(DefaultModel):
    author = models.ForeignKey(
        "user.Author",
        on_delete=models.CASCADE,
        related_name="institutions",
    )

    institution = models.ForeignKey(
        "institution.Institution",
        on_delete=models.CASCADE,
        related_name="author_institutions",
    )

    years = ArrayField(models.IntegerField(), blank=True, default=list)
