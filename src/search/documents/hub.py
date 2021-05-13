from django_elasticsearch_dsl import Document
from django_elasticsearch_dsl.fields import IntegerField
from django_elasticsearch_dsl.registries import registry

from hub.models import Hub
from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
import utils.sentry as sentry


@registry.register_document
class HubDocument(Document):
    paper_count = IntegerField(attr='paper_count_indexing')
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
            ELASTICSEARCH_AUTO_REINDEX is False
        )

        # Don't perform an index refresh after every update (overrides global
        # setting):
        auto_refresh = (TESTING is False) or (
            ELASTICSEARCH_AUTO_REINDEX is True
        )

    def update(self, *args, **kwargs):
        try:
            super().update(*args, **kwargs)
        except ConnectionError as e:
            sentry.log_info(e)
        except Exception as e:
            sentry.log_info(e)
