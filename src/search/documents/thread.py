from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from discussion.models import Thread
from researchhub.settings import (
    ELASTICSEARCH_AUTO_REINDEX,
    TESTING
)
from search.analyzers import title_analyzer
import utils.sentry as sentry


@registry.register_document
class ThreadDocument(Document):
    comment_count = es_fields.IntegerField(attr='comment_count_indexing')
    # TODO: Make this a nested user field with author inside
    created_by_author_profile = es_fields.ObjectField(
        attr='created_by_author_profile_indexing',
        properties={
            'id': es_fields.IntegerField(),
            'first_name': es_fields.TextField(),
            'last_name': es_fields.TextField(),
        }
    )
    paper = es_fields.IntegerField(attr='paper_indexing')
    paper_title = es_fields.TextField(
        attr='paper_title_indexing',
        analyzer=title_analyzer
    )
    score = es_fields.IntegerField(attr='score_indexing')
    plain_text = es_fields.TextField()
    title = es_fields.TextField(analyzer=title_analyzer)

    class Index:
        name = 'discussion_thread'

    class Django:
        model = Thread
        fields = [
            'id',
            'created_date',
            'updated_date',
            'is_public',
            'is_removed',
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

        # Paginate the django queryset used to populate the index with the
        # specified size (by default it uses the database driver's default
        # setting)
        # queryset_pagination = 5000

    def update(self, *args, **kwargs):
        try:
            super().update(*args, **kwargs)
        except ConnectionError as e:
            sentry.log_info(e)
        except Exception as e:
            sentry.log_info(e)
