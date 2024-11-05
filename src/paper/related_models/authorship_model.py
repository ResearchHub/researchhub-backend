from django.db import models
from django.utils.translation import gettext_lazy as _

from utils.models import DefaultModel


class Authorship(DefaultModel):
    class Source(models.TextChoices):
        AUTHOR_MIGRATION = "AUTHOR_MIGRATION", _("Author Migration")

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
    )

    paper = models.ForeignKey(
        "paper.paper",
        on_delete=models.CASCADE,
        related_name="authorships",
        blank=False,
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

    department = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    is_corresponding = models.BooleanField(
        default=False,
    )

    raw_author_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    source = models.TextField(
        choices=Source.choices,
        null=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "author"], name="unique_paper_author"
            )
        ]
