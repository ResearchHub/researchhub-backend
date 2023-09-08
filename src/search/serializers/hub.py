from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from hub.models import Hub
from search.documents import HubDocument


class HubDocumentSerializer(DocumentSerializer):
    document = HubDocument

    class Meta(object):
        model = Hub
        fields = [
            "id",
            "name",
            "description",
            "slug",
        ]
