from django_elasticsearch_dsl_drf.filter_backends import (
    OrderingFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search
from elasticsearch_dsl.query import SF, FunctionScore, Q

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.post import PostDocument
from search.serializers.post import PostDocumentSerializer
from utils.permissions import ReadOnly


class PostSuggesterDocumentView(DocumentViewSet):
    document = PostDocument
    permission_classes = [ReadOnly]
    serializer_class = PostDocumentSerializer
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
        "title": {"field": "title", "lookups": ["match"]},
    }
    multi_match_search_fields = {
        "title": {"field": "title", "boost": 1},
    }
    suggester_fields = {
        "title_suggest": {
            "field": "title_suggest",
            "suggesters": ["completion"],
            "options": {
                "size": 5,
            },
        },
    }

    def __init__(self, *args, **kwargs):
        self.search = Search(index=["paper"])
        super(PostSuggesterDocumentView, self).__init__(*args, **kwargs)

    def _filter_queryset(self, request):
        queryset = self.search

        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
                request,
                queryset,
                self,
            )

        return queryset
