from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from paper.models import Paper
from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from search.analyzers import (
    title_analyzer,
    name_analyzer,
    content_analyzer
) 
import utils.sentry as sentry

@registry.register_document
class PaperDocument(Document):
    hubs_flat = es_fields.TextField(attr='hubs_indexing_flat')
    discussion_count = es_fields.IntegerField(attr='discussion_count_indexing')
    score = es_fields.IntegerField(attr='score_indexing')
    hot_score = es_fields.IntegerField(attr='hot_score_indexing')
    summary = es_fields.TextField(attr='summary_indexing')
    title = es_fields.TextField(analyzer=title_analyzer)
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(attr='paper_publish_date', format='yyyy-MM-dd')
    abstract = es_fields.TextField(attr='abstract_indexing', analyzer=content_analyzer)
    doi = es_fields.TextField(attr='doi_indexing', analyzer='keyword')
    authors = es_fields.TextField(attr='authors_indexing', analyzer=name_analyzer)
    raw_authors = es_fields.ObjectField(
        attr='raw_authors_indexing',
        properties={
            'first_name': es_fields.TextField(),
            'last_name': es_fields.TextField(),
            'full_name': es_fields.TextField(),
        }
    )
    hubs = es_fields.ObjectField(
        attr='hubs_indexing',
        properties={
            'hub_image': es_fields.TextField(),
            'id': es_fields.IntegerField(),
            'is_locked': es_fields.TextField(),
            'is_removed': es_fields.TextField(),
            'name': es_fields.KeywordField(),
            'slug': es_fields.TextField(),
        }
    )



    class Index:
        name = 'paper'

    class Django:
        model = Paper
        fields = [
            'id',
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