from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from researchhub.settings import DEVELOPMENT, TESTING
from user.models import Author


@registry.register_document
class AuthorDocument(Document):
    user = es_fields.ObjectField()
    university = es_fields.ObjectField()

    class Index:
        name = 'authors'

    class Django:
        model = Author
        fields = [
            'first_name',
            'last_name',
            'created_date',
            'updated_date',
        ]

        # Ignore auto updating of Elasticsearch when a model is saved
        # or deleted:
        ignore_signals = (TESTING is True) or (DEVELOPMENT is True)

        # Don't perform an index refresh after every update (overrides global
        # setting):
        auto_refresh = (TESTING is False) or (DEVELOPMENT is False)
