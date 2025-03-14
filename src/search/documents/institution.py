from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from institution.models import Institution

from .base import BaseDocument


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
    suggestion_phrases = es_fields.Completion()
    works_count = es_fields.IntegerField()

    class Index:
        name = "institution"
        fields = ["id", "display_name"]

    class Django:
        model = Institution

    def should_remove_from_index(self, obj):
        return False

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
        data = super().prepare(instance)
        try:
            data["suggestion_phrases"] = self.prepare_suggestion_phrases(instance)
        except Exception as error:
            print(f"Error preparing suggestions for {instance.id}: {error}")
            data["suggestion_phrases"] = []
        return data
