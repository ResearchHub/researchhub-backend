from django_elasticsearch_dsl_drf.constants import SUGGESTER_COMPLETION
from django_elasticsearch_dsl_drf.filter_backends import SuggesterFilterBackend
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.user import UserDocument
from search.serializers.user import UserDocumentSerializer
from utils.permissions import ReadOnly


class UserDocumentView(DocumentViewSet):
    document = UserDocument
    permission_classes = [ReadOnly]
    serializer_class = UserDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        SuggesterFilterBackend,
    ]
    suggester_fields = {
        "full_name_suggest": {
            "field": "full_name_suggest",
            "suggesters": ["completion"],
            "options": {
                "size": 5,
            },
        },
    }
