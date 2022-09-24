from django.db import models
from utils.models import DefaultModel

# We ask openalex to classify a paper into concepts, which we then present as tag candidates from which users can pick zero or more to attach to the paper.
# TODO: migration
# https://docs.openalex.org/about-the-data/concept
class Concept(DefaultModel):

    # https://docs.openalex.org/about-the-data/concept#i
    openalex_id = models.CharField(
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
    description = models.TextField(default='', blank=True)

    # https://docs.openalex.org/about-the-data/concept#created_date
    openalex_created_date = models.CharField(
        blank=False,
        null=False,
        max_length=255,
    )

    # https://docs.openalex.org/about-the-data/concept#updated_date
    openalex_updated_date = models.CharField(
        blank=False,
        null=False,
        max_length=255,
    )
