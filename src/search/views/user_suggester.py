from django_elasticsearch_dsl_drf.filter_backends import (
    OrderingFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.user import UserDocument
from search.serializers.user import UserDocumentSerializer
from utils.permissions import ReadOnly


class UserSuggesterDocumentView(DocumentViewSet):
    document = UserDocument
    permission_classes = [ReadOnly]
    serializer_class = UserDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        MultiMatchSearchFilterBackend,
        SuggesterFilterBackend,
        OrderingFilterBackend,
    ]
    ordering = ("-reputation",)
    ordering_fields = {
        "reputation": "reputation",
    }
    filter_fields = {
        "full_name": {"field": "full_name", "lookups": ["match"]},
    }
    multi_match_search_fields = {
        "full_name": {"field": "full_name", "boost": 1},
    }
    suggester_fields = {
        "full_name_suggest": {
            "field": "full_name_suggest",
            "suggesters": ["completion"],
            "options": {
                "size": 5,
            },
        },
    }
