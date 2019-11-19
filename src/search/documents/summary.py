from django_elasticsearch_dsl import Document, fields as es_fields
# from django_elasticsearch_dsl.registries import registry

from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)

from summary.models import Summary
from search.analyzers import title_analyzer

# @registry.register_document  # Do we need summaries independent of papers?
class SummaryDocument(Document):
    summary_plain_text = es_fields.StringField(analyzer=title_analyzer)
    proposed_by = es_fields.ObjectField()
    previous = es_fields.ObjectField()
    paper = es_fields.ObjectField()
    approved = es_fields.BooleanField()
    approved_by = es_fields.ObjectField()

    class Index:
        name = 'summary'

    class Django:
        model = Summary
        fields = [
            'id',
            'summary_plain_text',
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
