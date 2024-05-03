from django.contrib.postgres.fields import ArrayField
from django.db import models

from utils.models import DefaultModel


class Topic(DefaultModel):
    # https://docs.openalex.org/api-entities/topics/topic-object#id
    openalex_id = models.CharField(
        unique=True,
        blank=False,
        null=False,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#display_name
    display_name = models.TextField(
        blank=False,
        null=False,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#domain
    domain_display_name = models.TextField(
        blank=True,
        null=True,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#domain
    domain_openalex_id = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#field
    field_display_name = models.TextField(
        blank=True,
        null=True,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#field
    field_openalex_id = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#subfield
    subfield_display_name = models.TextField(
        blank=True,
        null=True,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#subfield
    subfield_openalex_id = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#works_count
    works_count = models.IntegerField(
        blank=False,
        null=False,
        default=0,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#cited_by_count
    cited_by_count = models.IntegerField(
        blank=False,
        null=False,
        default=0,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#keywords
    keywords = ArrayField(
        models.CharField(max_length=255), blank=True, null=False, default=list
    )

    def upsert_from_openalex(oa_topic):
        mapped = {
            "openalex_id": oa_topic["id"],
            "updated_date": oa_topic["updated_date"],
            "display_name": oa_topic["display_name"],
            "domain_display_name": oa_topic["domain"]["display_name"],
            "domain_openalex_id": oa_topic["domain"]["id"],
            "field_display_name": oa_topic["field"]["display_name"],
            "field_openalex_id": oa_topic["field"]["id"],
            "subfield_display_name": oa_topic["subfield"]["display_name"],
            "subfield_openalex_id": oa_topic["subfield"]["id"],
            "works_count": oa_topic["works_count"],
            "cited_by_count": oa_topic["cited_by_count"],
            "keywords": oa_topic["keywords"],
        }

        topic = Topic.objects.filter(openalex_id=oa_topic["id"])

        if topic.exists():
            topic.update(**mapped)
        else:
            topic = Topic.objects.create(**mapped)
        return topic
