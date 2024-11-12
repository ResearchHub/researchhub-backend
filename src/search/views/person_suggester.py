from django_elasticsearch_dsl_drf.filter_backends import (
    OrderingFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.person import PersonDocument
from search.serializers.person import PersonDocumentSerializer
from utils.permissions import ReadOnly


class PersonSuggesterDocumentView(DocumentViewSet):
    document = PersonDocument
    permission_classes = [ReadOnly]
    serializer_class = PersonDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        MultiMatchSearchFilterBackend,
        SuggesterFilterBackend,
        OrderingFilterBackend,
    ]

    ordering = ("-author_score",)
    ordering_fields = {
        "id": "id",
        "full_name": "full_name",
        "author_score": "author_score",
    }

    filter_fields = {
        "full_name": {"field": "full_name", "lookups": ["match"]},
    }

    multi_match_search_fields = {
        "full_name": {"field": "full_name", "boost": 1},
    }

    suggester_fields = {
        "suggestion_phrases": {
            "field": "suggestion_phrases",
            "suggesters": ["completion"],
            "options": {
                "size": 5,
            },
        },
    }
