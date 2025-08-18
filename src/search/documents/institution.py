import logging

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from institution.models import Institution

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class InstitutionDocument(BaseDocument):
    id = es_fields.IntegerField()
    openalex_id = es_fields.TextField()
    display_name = es_fields.TextField()
    country_code = es_fields.KeywordField()
    ror_id = es_fields.KeywordField()
    city = es_fields.TextField()
    region = es_fields.TextField()
    longitude = es_fields.TextField()
    latitude = es_fields.TextField()
    image_url = es_fields.TextField()
    image_thumbnail_url = es_fields.TextField()
    two_year_mean_citedness = es_fields.FloatField()
    i10_index = es_fields.FloatField()
    h_index = es_fields.FloatField()
    suggestion_phrases = es_fields.CompletionField()
    works_count = es_fields.IntegerField()

    class Index:
        name = "institution"
        fields = ["id", "display_name"]

    class Django:
        model = Institution

    def prepare_suggestion_phrases(self, instance):
        suggestions = []

        suggestions.append({"input": instance.display_name, "weight": 10})

        for alt_name in instance.display_name_alternatives:
            suggestions.append({"input": alt_name, "weight": 5})

        if instance.country_code:
            suggestions.append({"input": instance.country_code, "weight": 2})

        if instance.city:
            suggestions.append({"input": instance.city, "weight": 2})

        if instance.region:
            suggestions.append({"input": instance.region, "weight": 2})

        if instance.openalex_id:
            suggestions.append({"input": instance.openalex_id, "weight": 100})

        if instance.ror_id:
            suggestions.append({"input": instance.ror_id, "weight": 100})

        return suggestions

    def prepare(self, instance):
        try:
            data = super().prepare(instance)
        except Exception:
            logger.error(f"Failed to prepare data for institution {instance.id}")
            return None

        try:
            data["suggestion_phrases"] = self.prepare_suggestion_phrases(instance)
        except Exception as e:
            logger.warning(
                f"Failed to prepare suggestion phrases for institution {instance.id}: {e}"
            )
            data["suggestion_phrases"] = []

        return data
