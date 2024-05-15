from datetime import datetime, timedelta

from django.db import models

from hub.models import Hub
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
    description = models.TextField(blank=True, null=False, default="")

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
        return datetime.now(self.updated_date.tzinfo) - self.updated_date > timedelta(
            days=30
        )

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        is_new_concept = not self.pk or not hasattr(self, "hub")
        super().save(*args, **kwargs)

        # Do not update hub props when concept is updated to avoid
        # overriding changes made by our system (e.g. hub name, description, etc.)
        if is_new_concept:
            Hub.create_or_update_hub_from_concept(concept=self)

    @classmethod
    def create_or_update(cls, paper_concept):
        stored_concept, created = cls.objects.get_or_create(
            openalex_id=paper_concept["openalex_id"],
            defaults={
                "display_name": paper_concept.get("display_name", ""),
                "description": paper_concept.get("description", ""),
                "openalex_created_date": paper_concept.get(
                    "openalex_created_date", None
                ),
                "openalex_updated_date": paper_concept.get(
                    "openalex_updated_date", None
                ),
            },
        )

        # update existing concept with fresh data from openalex
        stored_concept.display_name = paper_concept.get("display_name", "")
        stored_concept.description = paper_concept.get("description", "")
        stored_concept.openalex_created_date = paper_concept["openalex_created_date"]
        stored_concept.openalex_updated_date = paper_concept["openalex_updated_date"]
        stored_concept.save()

        return stored_concept

    @classmethod
    def upsert_from_openalex(cls, openalex_concept):
        mapped = {
            "openalex_id": openalex_concept["id"],
            "display_name": openalex_concept["display_name"],
        }

        # Add optional fields that may not exist if the concept is a dehydrated concept.
        # https://docs.openalex.org/api-entities/concepts/concept-object#the-dehydratedconcept-object
        if "description" in openalex_concept:
            mapped["description"] = openalex_concept["description"]
        if "updated_date" in openalex_concept:
            mapped["openalex_updated_date"] = openalex_concept["updated_date"]
        if "created_date" in openalex_concept:
            mapped["openalex_created_date"] = openalex_concept["created_date"]

        concept = None
        try:
            concept = Concept.objects.get(openalex_id=openalex_concept["id"])

            for key, value in mapped.items():
                setattr(concept, key, value)
            concept.save()
        except Concept.DoesNotExist:
            concept = cls.objects.create(**mapped)

        return concept
