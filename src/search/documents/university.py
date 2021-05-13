from django_elasticsearch_dsl import Document
from django_elasticsearch_dsl.registries import registry

from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from user.models import University
import utils.sentry as sentry


@registry.register_document
class UniversityDocument(Document):

    class Index:
        name = 'university'

    class Django:
        model = University
        fields = [
            'id',
            'name',
            'country',
            'state',
            'city',
        ]

        # Ignore auto updating of Elasticsearch when a model is saved
        # or deleted (defaults to False):
        ignore_signals = (TESTING is True) or (
            ELASTICSEARCH_AUTO_REINDEX is False
        )

        # Don't perform an index refresh after every update (False overrides
        # global setting of True):
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
