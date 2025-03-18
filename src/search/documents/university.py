import logging

from django_elasticsearch_dsl import Document
from django_elasticsearch_dsl.registries import registry

import utils.sentry as sentry
from user.models import University

logger = logging.getLogger(__name__)


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
        except Exception as e:
            logger.error(f"Failed to update university {self.instance.id}: {e}")
            sentry.log_info(e)
