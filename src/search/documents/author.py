from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from user.models import Author


@registry.register_document
class AuthorDocument(Document):
    user = es_fields.ObjectField()
    university = es_fields.ObjectField()

    class Django:
        model = Author
        fields = [
            'first_name',
            'last_name',
            'created_date',
            'updated_date',
        ]

    class Index:
        name = 'authors'
