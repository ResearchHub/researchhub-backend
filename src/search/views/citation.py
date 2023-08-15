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
from rest_framework.permissions import IsAuthenticated

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents import CitationEntryDocument
from search.serializers import CitationEntryDocumentSerializer
from utils.permissions import ReadOnly


class CitationEntryDocumentView(DocumentViewSet):
    document = CitationEntryDocument
    permission_classes = [ReadOnly, IsAuthenticated]
    serializer_class = CitationEntryDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        FilteringFilterBackend,
        SearchFilterBackend,
        # MultiMatchSearchFilterBackend,
        # SuggesterFilterBackend,
    ]
    # search_fields = ("title", "full_name", "fields")
    search_fields = ("title", "full_name")
    search_nested_fields = {"title": {"path": "fields", "fields": ["title"]}}

    filter_fields = {
        "created_by": {"field": "created_by.full_name"},
        "created_by_id": {"field": "created_by.id"},
        "organization": {"field": "organization.id"},
        "title": {"field": "title"},
        "title_test": {"field": "fields.title"}
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

    def _build_allowed_citations(self):
        request = self.request
        user = request.user
        organization = getattr(request, "organization", None)
        terms = [{"terms": {"created_by.id": [user.id]}}]
        if organization:
            organization_id = organization.id
        else:
            organization_id = 65
        terms.append({"terms": {"organization.id": [organization_id]}})
        return terms

    def get_queryset(self):
        queryset = super().get_queryset()
        _queries = self._build_allowed_citations()
        queryset = queryset.query("bool", filter=_queries)
        return queryset
