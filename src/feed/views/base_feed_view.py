from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets

from hub.models import Hub
from paper.related_models.paper_model import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


class BaseFeedView(viewsets.ModelViewSet):
    """
    Base class for feed-related viewsets.
    """

    _content_types = {}

    @property
    def _hub_content_type(self):
        return self._get_content_type(Hub)

    @property
    def _paper_content_type(self):
        return self._get_content_type(Paper)

    @property
    def _post_content_type(self):
        return self._get_content_type(ResearchhubPost)

    def _get_content_type(self, model_class):
        model_name = model_class.__name__.lower()
        if model_name not in self._content_types:
            self._content_types[model_name] = ContentType.objects.get_for_model(
                model_class
            )
        return self._content_types[model_name]
