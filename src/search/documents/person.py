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
