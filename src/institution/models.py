from django.contrib.postgres.fields import ArrayField
from django.db import models

from utils.models import DefaultModel
from utils.openalex import OpenAlex


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
        blank=True,
        null=True,
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

    # https://docs.openalex.org/api-entities/institutions/institution-object#geo
    city = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#region
    region = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#geo
    latitude = models.FloatField(
        blank=True,
        null=True,
    )

    # https://docs.openalex.org/api-entities/institutions/institution-object#geo
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

    openalex_created_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    openalex_updated_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    def upsert_from_openalex(oa_institution):
        has_dates = oa_institution.get("updated_date") and oa_institution.get(
            "created_date"
        )

        # Normalize created, updated dates to format that is compatible with django
        oa_institution = OpenAlex.normalize_dates(oa_institution)

        institution = None
        try:
            institution = Institution.objects.get(openalex_id=oa_institution["id"])
        except Institution.DoesNotExist:
            pass

        needs_update = False
        if institution and has_dates:
            needs_update = (not institution.openalex_updated_date) or (
                institution.openalex_updated_date < oa_institution["updated_date"]
            )

        mapped = {
            "openalex_id": oa_institution.get("id"),
            "updated_date": oa_institution.get("updated_date"),
            "display_name": oa_institution.get("display_name"),
            "ror_id": oa_institution.get("ror"),
            "country_code": oa_institution.get("country_code"),
            "type": oa_institution.get("type"),
            "lineage": oa_institution.get("lineage"),
            "city": oa_institution.get("geo", {}).get("city"),
            "region": oa_institution.get("geo", {}).get("region"),
            "latitude": oa_institution.get("geo", {}).get("latitude"),
            "longitude": oa_institution.get("geo", {}).get("longitude"),
            "image_url": oa_institution.get("image_url"),
            "image_thumbnail_url": oa_institution.get("image_thumbnail_url"),
            "two_year_mean_citedness": oa_institution.get("summary_stats", {}).get(
                "2yr_mean_citedness"
            ),
            "h_index": oa_institution.get("summary_stats", {}).get("h_index"),
            "i10_index": oa_institution.get("summary_stats", {}).get("i10_index"),
            "works_count": oa_institution.get("works_count"),
            "associated_institutions": list(
                map(
                    lambda obj: obj["id"], oa_institution.get("associated_institutions")
                )
            ),
            "display_name_alternatives": oa_institution.get(
                "display_name_alternatives"
            ),
        }

        if needs_update:
            for key, value in mapped.items():
                setattr(institution, key, value)
            institution.save()
        else:
            institution = Institution.objects.create(**mapped)
        return institution
