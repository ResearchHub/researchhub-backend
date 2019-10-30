from django_elasticsearch_dsl_drf.constants import (
    LOOKUP_FILTER_TERMS,
    LOOKUP_FILTER_RANGE,
    LOOKUP_FILTER_PREFIX,
    LOOKUP_FILTER_WILDCARD,
    LOOKUP_QUERY_IN,
    LOOKUP_QUERY_GT,
    LOOKUP_QUERY_GTE,
    LOOKUP_QUERY_LT,
    LOOKUP_QUERY_LTE,
    LOOKUP_QUERY_EXCLUDE,
)
from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    HighlightBackend,
    FilteringFilterBackend,
    NestedFilteringFilterBackend,
    IdsFilterBackend,
    OrderingFilterBackend,
)
from django_elasticsearch_dsl_drf.viewsets import BaseDocumentViewSet
from django_elasticsearch_dsl_drf.pagination import PageNumberPagination

from search.documents.paper import PaperDocument
from search.serializers.paper import PaperDocumentSerializer


class PaperDocumentView(BaseDocumentViewSet):
    document = PaperDocument
    serializer_class = PaperDocumentSerializer
    pagination_class = PageNumberPagination
    lookup_field = 'id'
    filter_backends = [
        CompoundSearchFilterBackend,
        DefaultOrderingFilterBackend,
        FilteringFilterBackend,
        # NestedFilteringFilterBackend,
        IdsFilterBackend,
        OrderingFilterBackend,
        HighlightBackend,
    ]

    search_fields = [
        'title',
        'tagline',
        'doi',
        'authors',
    ]

    ordering_fields = {
        'score': 'score',
    }

    highlight_fields = {
        'title': {
            'options': {
                'pre_tags': ["<b>"],
                'post_tags': ["</b>"],
            },
        },
    }
