from django_elasticsearch_dsl_drf.constants import SUGGESTER_COMPLETION
from django_elasticsearch_dsl_drf.filter_backends import (
    FilteringFilterBackend,
    OrderingFilterBackend,
    SearchFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents import CitationEntryDocument
from search.serializers import CitationEntryDocumentSerializer
from utils.permissions import ReadOnly


class CitationEntryDocumentView(DocumentViewSet):
    document = CitationEntryDocument
    permission_classes = [ReadOnly]
    serializer_class = CitationEntryDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        FilteringFilterBackend,
        SearchFilterBackend,
        # MultiMatchSearchFilterBackend,
        # SuggesterFilterBackend,
    ]
    search_fields = ("title", "full_name")
    filter_fields = {
        "title": {"field": "title"},
        "created_by": {"field": "created_by.full_name"},
        # "first_name": {"field": "full_name", "lookups": ["match"]},
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
