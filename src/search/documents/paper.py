from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from paper.models import Paper
from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from search.analyzers import title_analyzer
import utils.sentry as sentry


@registry.register_document
class PaperDocument(Document):
    authors = es_fields.TextField(attr='authors_indexing')
    discussion_count = es_fields.IntegerField(attr='discussion_count_indexing')
    hubs = es_fields.TextField(attr='hubs_indexing')
    score = es_fields.IntegerField(attr='score_indexing')
    summary = es_fields.TextField(attr='summary_indexing')
    title = es_fields.TextField(analyzer=title_analyzer)
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    abstract = es_fields.TextField(attr='abstract_indexing')

    class Index:
        name = 'paper'

    class Django:
        model = Paper
        fields = [
            'id',
            'doi',
            'paper_publish_date',
            'publication_type',
            'url',
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
