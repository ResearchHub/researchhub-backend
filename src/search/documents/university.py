from django_elasticsearch_dsl import Document
from django_elasticsearch_dsl.registries import registry

import utils.sentry as sentry
from user.models import University


@registry.register_document
class UniversityDocument(Document):

    class Index:
        name = "university"

    class Django:
        model = University
        fields = [
            "id",
            "name",
            "country",
            "state",
            "city",
        ]

    def update(self, *args, **kwargs):
        try:
            super().update(*args, **kwargs)
        except ConnectionError as e:
            sentry.log_info(e)
        except Exception as e:
            sentry.log_info(e)
