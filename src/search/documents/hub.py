from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from hub.models import Hub
from .base import BaseDocument

from search.analyzers import (
    title_analyzer,
    content_analyzer
)


@registry.register_document
class HubDocument(BaseDocument):
    auto_refresh = True

    paper_count = es_fields.IntegerField(attr='paper_count')
    subscriber_count = es_fields.IntegerField(attr='subscriber_count')
    discussion_count = es_fields.IntegerField(attr='discussion_count')
    description = es_fields.TextField(attr='description', analyzer=content_analyzer)
    name = es_fields.TextField(attr='name', analyzer=title_analyzer)

    class Index:
        name = 'hub'

    class Django:
        model = Hub
        fields = [
            'id',
            'acronym',
            'is_locked',
        ]


    def should_remove_from_index(self, obj):
        if obj.is_removed or obj.is_locked:
            return True

        return False