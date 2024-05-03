from django.contrib.postgres.fields import ArrayField
from django.db import models

from utils.models import DefaultModel


class Institution(DefaultModel):
    # e.g. https://openalex.org/S1983995261
    # https://docs.openalex.org/api-entities/institutions/institution-object#id
    openalex_id = models.CharField(
        unique=True,
        blank=False,
        null=False,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#ror
    ror_id = models.CharField(
        unique=True,
        blank=False,
        null=False,
        max_length=100,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#display_name
    display_name = models.TextField(
        blank=False,
        null=False,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#country_code
    country_code = models.CharField(
        blank=False,
        null=False,
        max_length=20,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#type
    type = models.CharField(
        blank=False,
        null=False,
        max_length=60,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#lineage
    lineage = ArrayField(
        models.CharField(max_length=255), blank=True, null=False, default=list
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#city
    city = models.CharField(
        blank=False,
        null=False,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#region
    region = models.CharField(
        blank=False,
        null=False,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#latitude
    latitude = models.FloatField(
        blank=True,
        null=True,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#longitude
    longitude = models.FloatField(
        blank=True,
        null=True,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#image_url
    image_url = models.CharField(
        blank=True,
        null=True,
        max_length=500,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#image_thumbnail_url
    image_thumbnail_url = models.CharField(
        blank=True,
        null=True,
        max_length=500,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#2yr_mean_citedness
    two_year_mean_citedness = models.FloatField(blank=False, null=False, default=0)

    # https://docs.openalex.org/api-entities/institutions/institution-object#summary_stats
    h_index = models.IntegerField(blank=False, null=False, default=0)

    # https://docs.openalex.org/api-entities/institutions/institution-object#summary_stats
    i10_index = models.IntegerField(blank=False, null=False, default=0)

    # https://docs.openalex.org/api-entities/institutions/institution-object#works_count
    works_count = models.IntegerField(blank=False, null=False, default=0)

    # https://docs.openalex.org/api-entities/institutions/institution-object#associated_institutions
    associated_institutions = ArrayField(
        models.CharField(blank=False, null=False, max_length=500)
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#display_name_alternatives
    display_name_alternatives = ArrayField(
        models.CharField(max_length=255), blank=True, null=False, default=list
    )
