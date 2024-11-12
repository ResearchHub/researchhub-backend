from django_elasticsearch_dsl_drf.filter_backends import (
    OrderingFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.institution import InstitutionDocument
from search.serializers.institution import InstitutionDocumentSerializer
from utils.permissions import ReadOnly


class InstitutionSuggesterDocumentView(DocumentViewSet):
    document = InstitutionDocument
    permission_classes = [ReadOnly]
    serializer_class = InstitutionDocumentSerializer
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
        "full_name": "full_name",
        "display_name": "display_name",
    }

    filter_fields = {
        "display_name": {"field": "display_name", "lookups": ["match"]},
    }

    multi_match_search_fields = {
        "display_name": {"field": "display_name", "boost": 1},
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
