from django_elasticsearch_dsl_drf.filter_backends import (
    OrderingFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.hub import HubDocument
from search.serializers.hub import HubDocumentSerializer
from utils.permissions import ReadOnly


class HubSuggesterDocumentView(DocumentViewSet):
    document = HubDocument
    permission_classes = [ReadOnly]
    serializer_class = HubDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        MultiMatchSearchFilterBackend,
        SuggesterFilterBackend,
        OrderingFilterBackend,
    ]
    ordering = ("-id",)
    ordering_fields = {
        "id": "id",
    }
    filter_fields = {
        "name": {"field": "name", "lookups": ["match"]},
    }
    multi_match_search_fields = {
        "name": {"field": "name", "boost": 1},
    }
    suggester_fields = {
        "name_suggest": {
            "field": "name_suggest",
            "suggesters": ["completion"],
            "options": {
                "size": 5,
            },
        },
    }
