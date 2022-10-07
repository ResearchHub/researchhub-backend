from datetime import datetime, timedelta

from django.db import models
from utils.models import DefaultModel

# We ask openalex to classify a paper into concepts, which we then present as tag candidates from which users can pick
# zero or more to attach to the paper. https://docs.openalex.org/about-the-data/concept
class Concept(DefaultModel):

    # e.g. "https://openalex.org/C2524010"
    # https://docs.openalex.org/about-the-data/concept#id
    openalex_id = models.CharField(
        unique=True,
        blank=False,
        null=False,
        max_length=255,
    )

    # https://docs.openalex.org/about-the-data/concept#display_name
    display_name = models.CharField(
        blank=False,
        null=False,
        max_length=255,
    )

    # https://docs.openalex.org/about-the-data/concept#description
    description = models.TextField(
        blank=True,
        null=False,
        default='')

    # e.g. "2016-06-24"
    # https://docs.openalex.org/about-the-data/concept#created_date
    openalex_created_date = models.CharField(
        blank=False,
        null=False,
        max_length=255,
    )

    # e.g. "2022-09-29T07:50:07.737330"
    # https://docs.openalex.org/about-the-data/concept#updated_date
    openalex_updated_date = models.CharField(
        blank=False,
        null=False,
        max_length=255,
    )

    def needs_refresh(self):
        return datetime.now(self.updated_date.tzinfo) - self.updated_date > timedelta(days=30)

    def __str__(self):
        return self.display_name


