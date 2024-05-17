from django.db import models

from utils.models import DefaultModel


class WorkAuthorship(DefaultModel):
    FIRST_AUTHOR_POSITION = "first"
    MIDDLE_AUTHOR_POSITION = "middle"
    LAST_AUTHOR_POSITION = "last"

    POSITION_CHOICES = [
        (FIRST_AUTHOR_POSITION, "First"),
        (MIDDLE_AUTHOR_POSITION, "Middle"),
        (LAST_AUTHOR_POSITION, "Last"),
    ]

    institutions = models.ManyToManyField(
        "institution.Institution",
        related_name="authors",
        blank=True,
        null=True,
    )

    author = models.ForeignKey(
        "user.Author",
        on_delete=models.CASCADE,
        related_name="authorships",
    )

    author_position = models.CharField(
        max_length=10,
        choices=POSITION_CHOICES,
        null=False,
        blank=False,
    )

    is_corresponding = models.BooleanField(
        default=False,
    )

    raw_author_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
