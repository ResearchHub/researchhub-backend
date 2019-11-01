from django_elasticsearch_dsl import Document
from django_elasticsearch_dsl.fields import IntegerField
from django_elasticsearch_dsl.registries import registry

from hub.models import Hub


@registry.register_document
class HubDocument(Document):
    subscriber_count = IntegerField(attr='subscriber_count_indexing')

    class Django:
        model = Hub
        fields = [
            'name',
            'is_locked',
            'created_date',
            'updated_date',
        ]

    class Index:
        name = 'hubs'
