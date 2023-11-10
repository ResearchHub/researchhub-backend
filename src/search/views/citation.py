from django_elasticsearch_dsl_drf.filter_backends import (
    FilteringFilterBackend,
    SearchFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from rest_framework.permissions import IsAuthenticated

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
    ]
    search_fields = ("title", "authors", "doi", "fields", "journal_name", "source")
    search_nested_fields = {
        "title": {"path": "fields", "fields": ["title"]},
        "source": {"path": "fields", "fields": ["source"]},
        "journal_name": {"path": "fields", "fields": ["container-title"]},
        "authors": {
            "path": "fields",
            "fields": ["author.given", "author.family"],
        },
    }

    filter_fields = {
        "created_by": {"field": "created_by.full_name"},
        "created_by_id": {"field": "created_by.id"},
        "organization": {"field": "organization.id"},
        "title": {"field": "title"},
    }

    def _build_allowed_citations(self):
        request = self.request
        user = request.user
        organization = getattr(request, "organization", None)
        terms = [{"terms": {"created_by.id": [user.id]}}]
        if organization:
            organization_id = organization.id
        else:
            organization_id = user.organization.id
        terms.append({"terms": {"organization.id": [organization_id]}})
        return terms

    def get_queryset(self):
        queryset = super().get_queryset()
        _queries = self._build_allowed_citations()
        queryset = queryset.query("bool", filter=_queries)
        return queryset
