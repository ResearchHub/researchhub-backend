from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from user.models import Author
import utils.sentry as sentry


@registry.register_document
class AuthorDocument(Document):
    profile_image = es_fields.TextField(attr='profile_image_indexing')
    university = es_fields.ObjectField(
        attr='university_indexing',
        properties={
            'name': es_fields.TextField(),
            'city': es_fields.TextField(),
            'country': es_fields.TextField(),
            'state': es_fields.TextField(),
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
