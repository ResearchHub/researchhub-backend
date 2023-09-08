from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from hub.models import Hub
from search.documents import HubDocument


class HubDocumentSerializer(DocumentSerializer):
    class Meta(object):
        document = HubDocument
        fields = [
            "id",
            "name",
            "description",
            "slug",
        ]
