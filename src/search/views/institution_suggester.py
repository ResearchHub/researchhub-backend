from rest_framework.decorators import action

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.base.filters import OrderingFilterBackend, SuggesterFilterBackend
from search.base.pagination import LimitOffsetPagination
from search.base.viewsets import ElasticsearchViewSet
from search.documents.institution import InstitutionDocument
from search.serializers.institution import InstitutionDocumentSerializer
from utils.permissions import ReadOnly


class InstitutionSuggesterDocumentView(ElasticsearchViewSet):
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
            "type": "completion",
        },
    }

    @action(detail=False, methods=["get"])
    def suggest(self, request, *args, **kwargs):
        """
        Suggest endpoint for backward compatibility.
        Delegates to the list view which handles suggestions via query params.
        """
        return self.list(request, *args, **kwargs)
