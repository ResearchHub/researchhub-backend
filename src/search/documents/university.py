from django_elasticsearch_dsl import Document
from django_elasticsearch_dsl.registries import registry

from researchhub.settings import DEVELOPMENT, TESTING
from user.models import University


@registry.register_document
class UniversityDocument(Document):

    class Index:
        name = 'university'

    class Django:
        model = University
        fields = [
            'id',
            'name',
            'country',
            'state',
            'city',
        ]

        # Ignore auto updating of Elasticsearch when a model is saved
        # or deleted:
        ignore_signals = (TESTING is True) or (DEVELOPMENT is True)

        # Don't perform an index refresh after every update (overrides global
        # setting):
        auto_refresh = (TESTING is False) or (DEVELOPMENT is False)
