from django_elasticsearch_dsl_drf.constants import SUGGESTER_COMPLETION
from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    FilteringFilterBackend,
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


class HubDocumentView(DocumentViewSet):
    document = HubDocument
    permission_classes = [ReadOnly]
    serializer_class = HubDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        CompoundSearchFilterBackend,
        DefaultOrderingFilterBackend,
        MultiMatchSearchFilterBackend,
        SuggesterFilterBackend,
    ]
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

    search_fields = {
        "name": {"boost": 1, "fuzziness": 1},
        "acronym": {"boost": 1, "fuzziness": 1},
        "description": {"boost": 1, "fuzziness": 1},
    }

    def __init__(self, *args, **kwargs):
        self.search = Search(index=["hub"])
        super(HubDocumentView, self).__init__(*args, **kwargs)

    def _filter_queryset(self, request):
        queryset = self.search

        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
                request,
                queryset,
                self,
            )

        return queryset
