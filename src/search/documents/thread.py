from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from discussion.models import Thread
from researchhub.settings import DEVELOPMENT, TESTING


@registry.register_document
class ThreadDocument(Document):
    paper = es_fields.StringField(attr='paper_indexing')
    text = es_fields.StringField(attr='text_indexing')

    class Index:
        name = 'discussion_thread'

    class Django:
        model = Thread
        fields = [
            'id',
            'title',
            'created_date',
            'updated_date',
            'is_public',
            'is_removed',
        ]

        # Ignore auto updating of Elasticsearch when a model is saved
        # or deleted:
        ignore_signals = (TESTING is True) or (DEVELOPMENT is True)

        # Don't perform an index refresh after every update (overrides global
        # setting):
        auto_refresh = (TESTING is False) or (DEVELOPMENT is False)

        # Paginate the django queryset used to populate the index with the
        # specified size (by default it uses the database driver's default
        # setting)
        # queryset_pagination = 5000
