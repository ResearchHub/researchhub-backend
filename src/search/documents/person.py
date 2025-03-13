import logging

from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from search.analyzers import content_analyzer
from user.models import Author

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PersonDocument(BaseDocument):
    profile_image = es_fields.TextField(attr="profile_image_indexing")
    user_reputation = es_fields.IntegerField(attr="user_reputation_indexing")
    author_score = es_fields.IntegerField(attr="author_score")
    description = es_fields.TextField(attr="description", analyzer=content_analyzer)
    full_name = es_fields.TextField(attr="full_name", analyzer=content_analyzer)
    person_types = es_fields.KeywordField(attr="person_types_indexing")
    headline = es_fields.ObjectField(
        properties={
            "title": es_fields.TextField(),
        },
    )
    institutions = es_fields.ObjectField(
        attr="institutions_indexing",
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.TextField(),
        },
    )
    suggestion_phrases = es_fields.Completion()
    user_id = es_fields.IntegerField(attr="user_id")
    reputation_hubs = es_fields.KeywordField()
    education = es_fields.KeywordField()
    created_date = es_fields.DateField(attr="created_date")

    class Index:
        name = "person"

    class Django:
        model = Author
        fields = [
            "id",
            "first_name",
            "last_name",
        ]

    def should_remove_from_index(self, obj):
        return False

    def prepare_headline(self, instance):
        return instance.build_headline()

    def prepare_reputation_hubs(self, instance):
        reputation_hubs = []
        for rep in instance.reputation_list:
            reputation_hubs.append(rep["hub"]["name"])

        return reputation_hubs

    def prepare_education(self, instance):
        education = []
        for edu in instance.education:
            education.append(edu["name"])

        return education

    def prepare_suggestion_phrases(self, instance):
        suggestions = []

        if instance.full_name:
            if instance.user:
                suggestions.append({"input": instance.full_name, "weight": 15})
            else:
                suggestions.append({"input": instance.full_name, "weight": 10})

        if instance.first_name:
            suggestions.append({"input": instance.first_name, "weight": 5})
        if instance.last_name:
            suggestions.append({"input": instance.last_name, "weight": 5})

        # Add institution names
        for author_institution in instance.institutions.all():
            if author_institution.institution.display_name:
                suggestions.append(
                    {"input": author_institution.institution.display_name, "weight": 3}
                )

                # Add full name + institution to account for people typing name + institution
                suggestions.append(
                    {
                        "input": instance.first_name
                        + " "
                        + author_institution.institution.display_name,
                        "weight": 3,
                    }
                )

        return suggestions

    def prepare(self, instance):
        data = super().prepare(instance)
        try:
            data["suggestion_phrases"] = self.prepare_suggestion_phrases(instance)
        except Exception as e:
            logger.error(f"Error preparing data for {instance.id}: {e}")
            data["suggestion_phrases"] = []
        return data
