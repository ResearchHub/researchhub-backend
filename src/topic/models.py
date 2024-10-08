import datetime

from dateutil import parser
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.timezone import get_current_timezone, is_aware, make_aware

from hub.models import Hub
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultModel
from utils.openalex import OpenAlex


class Domain(DefaultModel):
    # https://docs.openalex.org/api-entities/topics/topic-object#domain
    openalex_id = models.CharField(
        unique=True,
        blank=False,
        null=False,
        max_length=255,
    )

    display_name = models.TextField(
        blank=False,
        null=False,
    )


class Field(DefaultModel):
    # https://docs.openalex.org/api-entities/topics/topic-object#field
    openalex_id = models.CharField(
        unique=True,
        blank=False,
        null=False,
        max_length=255,
    )

    domain = models.ForeignKey(
        "topic.Domain",
        related_name="fields",
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    display_name = models.TextField(
        blank=False,
        null=False,
    )


class Subfield(DefaultModel):
    # https://docs.openalex.org/api-entities/topics/topic-object#subfield
    openalex_id = models.CharField(
        unique=True,
        blank=False,
        null=False,
        max_length=255,
    )

    field = models.ForeignKey(
        "topic.Field",
        related_name="subfields",
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    display_name = models.TextField(
        blank=False,
        null=False,
    )


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

    subfield = models.ForeignKey(
        "topic.Subfield",
        related_name="topics",
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#works_count
    works_count = models.IntegerField(
        blank=True,
        null=True,
        default=0,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#cited_by_count
    cited_by_count = models.IntegerField(
        blank=True,
        null=True,
        default=0,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#keywords
    keywords = ArrayField(
        models.CharField(max_length=255), blank=True, null=True, default=list
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#created_date
    openalex_created_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    # https://docs.openalex.org/api-entities/topics/topic-object#updated_date
    openalex_updated_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    def upsert_from_openalex(oa_topic):
        has_dates = oa_topic.get("updated_date") and oa_topic.get("created_date")

        # Normalize created, updated dates to format that is compatible with django
        oa_topic = OpenAlex.normalize_dates(oa_topic)

        topic = None
        try:
            topic = Topic.objects.get(openalex_id=oa_topic["id"])
        except Topic.DoesNotExist:
            pass

        # if topic exists, determine if we need to update it
        needs_update = False
        if topic and has_dates:
            needs_update = (not topic.openalex_updated_date) or (
                topic.openalex_updated_date < oa_topic["updated_date"]
            )

        # Upsert domain
        domain = None
        try:
            domain = Domain.objects.get(openalex_id=oa_topic["domain"]["id"])
        except Domain.DoesNotExist:
            pass

        if not domain:
            domain = Domain.objects.create(
                **{
                    "openalex_id": oa_topic["domain"]["id"],
                    "display_name": oa_topic["domain"]["display_name"],
                }
            )
        elif needs_update:
            domain.openalex_id = oa_topic["domain"]["id"]
            domain.display_name = oa_topic["domain"]["display_name"]
            domain.save()

        # Upsert field
        field = None
        try:
            field = Field.objects.get(openalex_id=oa_topic["field"]["id"])
        except Field.DoesNotExist:
            pass

        if not field:
            field = Field.objects.create(
                **{
                    "openalex_id": oa_topic["field"]["id"],
                    "display_name": oa_topic["field"]["display_name"],
                    "domain_id": domain.id,
                }
            )
        elif needs_update:
            field.openalex_id = oa_topic["field"]["id"]
            field.display_name = oa_topic["field"]["display_name"]
            field.save()

        # Upsert subfield
        subfield = None
        try:
            subfield = Subfield.objects.get(openalex_id=oa_topic["subfield"]["id"])
        except Subfield.DoesNotExist:
            pass

        if not subfield:
            subfield = Subfield.objects.create(
                **{
                    "openalex_id": oa_topic["subfield"]["id"],
                    "display_name": oa_topic["subfield"]["display_name"],
                    "field_id": field.id,
                }
            )

        elif needs_update:
            subfield.openalex_id = oa_topic["subfield"]["id"]
            subfield.display_name = oa_topic["subfield"]["display_name"]
            subfield.save()

        # Create hub associated with subfield if one does not already exist
        # Subfield hubs will be used for reputation calculation.
        try:
            created = False
            hub = None
            try:
                hub = Hub.get_from_subfield(subfield)
            except Hub.DoesNotExist:
                pass

            if not hub:
                hub, created = Hub.objects.create(
                    name=subfield.display_name,
                    subfield=subfield,
                    is_used_for_rep=True,
                )

            if created:
                print(
                    f"Created new hub {hub.name} and associated with subfield {subfield.display_name}."
                )
            else:
                hub.subfield = subfield
                hub.is_used_for_rep = True
                hub.save()
        except Exception as e:
            pass
            print(f"Error creating hub {subfield.display_name}: {e}")

        # Upsert topic
        mapped = {
            "openalex_id": oa_topic.get("id"),
            "display_name": oa_topic.get("display_name"),
            "works_count": oa_topic.get("works_count"),
            "cited_by_count": oa_topic.get("cited_by_count"),
            "keywords": oa_topic.get("keywords"),
            "subfield_id": subfield.id,
            "openalex_updated_date": oa_topic.get("updated_date"),
            "openalex_created_date": oa_topic.get("created_date"),
        }

        if not topic:
            topic = Topic.objects.create(**mapped)
        elif needs_update:
            for key, value in mapped.items():
                setattr(topic, key, value)

            topic.save()

        return topic


class UnifiedDocumentTopics(DefaultModel):
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
    )

    topic = models.ForeignKey(
        "topic.Topic",
        related_name="through_unified_document",
        blank=True,
        on_delete=models.CASCADE,
    )

    relevancy_score = models.FloatField(
        default=0.0,
    )

    is_primary = models.BooleanField(
        default=False,
    )

    class Meta:
        unique_together = ("unified_document", "topic")
