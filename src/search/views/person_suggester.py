from rest_framework.decorators import action

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.base.filters import OrderingFilterBackend, SuggesterFilterBackend
from search.base.pagination import LimitOffsetPagination
from search.base.viewsets import ElasticsearchViewSet
from search.documents.person import PersonDocument
from search.serializers.person import PersonDocumentSerializer
from utils.permissions import ReadOnly


class PersonSuggesterDocumentView(ElasticsearchViewSet):
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
