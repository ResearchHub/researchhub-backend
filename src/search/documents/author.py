from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from researchhub.settings import DEVELOPMENT, TESTING
from user.models import Author


@registry.register_document
class AuthorDocument(Document):
    university = es_fields.ObjectField(
        attr='university_indexing',
        properties={
            'name': es_fields.StringField(),
            'city': es_fields.StringField(),
            'country': es_fields.StringField(),
            'state': es_fields.StringField(),
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
        ignore_signals = (TESTING is True) or (DEVELOPMENT is True)

        # Don't perform an index refresh after every update (overrides global
        # setting):
        auto_refresh = (TESTING is False) or (DEVELOPMENT is False)
