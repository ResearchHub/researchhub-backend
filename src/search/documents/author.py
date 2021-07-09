from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from user.models import Author
from .base import BaseDocument

from search.analyzers import (
    content_analyzer
)

@registry.register_document
class AuthorDocument(BaseDocument):
    profile_image = es_fields.TextField(attr='profile_image_indexing')
    author_score = es_fields.IntegerField(attr='author_score')
    description = es_fields.TextField(attr='description', analyzer=content_analyzer)
    full_name = es_fields.TextField(attr='full_name', analyzer=content_analyzer)
    headline = es_fields.ObjectField(
        attr='headline',
        properties={
            'title': es_fields.TextField(),
        }
    )

    class Index:
        name = 'author'

    class Django:
        model = Author
        fields = [
            'id',
            'first_name',
            'last_name',
        ]
