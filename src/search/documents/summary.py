from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from search.analyzers import title_analyzer
from summary.models import Summary
import utils.sentry as sentry


@registry.register_document
class SummaryDocument(Document):
    summary_plain_text = es_fields.TextField(analyzer=title_analyzer)
    proposed_by = es_fields.TextField(attr='proposed_by_indexing')
    paper = es_fields.IntegerField(attr='paper_indexing')
    paper_title = es_fields.TextField(
        attr='paper_title_indexing',
        analyzer=title_analyzer
    )
    approved = es_fields.BooleanField()

    class Index:
        name = 'summary'

    class Django:
        model = Summary
        fields = [
            'id',
            'approved_date',
            'created_date',
            'updated_date',
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
