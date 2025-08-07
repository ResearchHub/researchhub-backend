from rest_framework.decorators import action

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.base.filters import OrderingFilterBackend, SuggesterFilterBackend
from search.base.pagination import LimitOffsetPagination
from search.base.viewsets import ElasticsearchViewSet
from search.documents.hub import HubDocument
from search.serializers.hub import HubDocumentSerializer
from utils.permissions import ReadOnly


class HubSuggesterDocumentView(ElasticsearchViewSet):
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

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return super().get_queryset()

    @action(detail=False, methods=["get"])
    def suggest(self, request, *args, **kwargs):
        """
        Suggest endpoint for backward compatibility.
        Delegates to the list view which handles suggestions via query params.
        """
        return self.list(request, *args, **kwargs)

    ordering = ("-paper_count",)
    ordering_fields = {"id": "id", "name": "name", "paper_count": "paper_count"}
    filter_fields = {
        "name": {"field": "name", "lookups": ["match"]},
    }
    multi_match_search_fields = {
        "name": {"field": "name", "boost": 1},
    }
    suggester_fields = {
        "name_suggest": {
            "field": "name_suggest",
            "type": "completion",
        },
    }
