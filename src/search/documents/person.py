from django_elasticsearch_dsl import Completion, Document
from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from search.analyzers import content_analyzer
from user.models import Author, User

from .base import BaseDocument


@registry.register_document
class PersonDocument(BaseDocument):
    profile_image = es_fields.TextField(attr="profile_image_indexing")
    user_reputation = es_fields.IntegerField(attr="user_reputation_indexing")
    author_score = es_fields.IntegerField(attr="author_score")
    description = es_fields.TextField(attr="description", analyzer=content_analyzer)
    full_name = es_fields.TextField(attr="full_name", analyzer=content_analyzer)
    person_types = es_fields.KeywordField(attr="person_types_indexing")
    headline = es_fields.ObjectField(
        attr="headline",
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

    def prepare_suggestion_phrases(self, instance):
        suggestions = []

        if instance.full_name:
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
        except Exception as error:
            print(f"Error preparing suggestions for {instance.id}: {error}")
            data["suggestion_phrases"] = []
        return data
