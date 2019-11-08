from django_elasticsearch_dsl import Document
from django_elasticsearch_dsl.fields import IntegerField
from django_elasticsearch_dsl.registries import registry

from hub.models import Hub
from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX_IN_DEVELOPMENT,
    TESTING
)


@registry.register_document
class HubDocument(Document):
    subscriber_count = IntegerField(attr='subscriber_count_indexing')

    class Index:
        name = 'hub'

    class Django:
        model = Hub
        fields = [
            'id',
            'name',
            'acronym',
            'is_locked',
        ]

        # Ignore auto updating of Elasticsearch when a model is saved
        # or deleted:
        ignore_signals = (TESTING is True) or (
            ELASTICSEARCH_AUTO_REINDEX_IN_DEVELOPMENT is False
        )

        # Don't perform an index refresh after every update (overrides global
        # setting):
        auto_refresh = (TESTING is False) or (
            ELASTICSEARCH_AUTO_REINDEX_IN_DEVELOPMENT is True
        )
