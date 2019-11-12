from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from paper.models import Paper


@registry.register_document
class PaperDocument(Document):
    authors = es_fields.StringField(attr='authors_indexing')
    discussion_count = es_fields.IntegerField(attr='discussion_count_indexing')
    hubs = es_fields.StringField(attr='hubs_indexing')
    score = es_fields.IntegerField(attr='score_indexing')
    summary = es_fields.StringField(attr='summary_indexing')

    class Index:
        name = 'paper'

    class Django:
        model = Paper
        fields = [
            'id',
            'doi',
            'paper_publish_date',
            'publication_type',
            'tagline',
            'title',
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
