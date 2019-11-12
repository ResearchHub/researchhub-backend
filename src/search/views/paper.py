# TODO: Refactor this to remove drf package
# flake8: noqa

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
    SUGGESTER_COMPLETION,
    SUGGESTER_PHRASE,
    SUGGESTER_TERM,
)
from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    HighlightBackend,
    FilteringFilterBackend,
    NestedFilteringFilterBackend,
    IdsFilterBackend,
    OrderingFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import PageNumberPagination

from search.documents.paper import PaperDocument
from search.serializers.paper import PaperDocumentSerializer


class PaperDocumentView(DocumentViewSet):
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
        SuggesterFilterBackend,  # This should be the last backend
    ]

    search_fields = [
        'title',
        'tagline',
        'doi',
        'authors',
    ]

    filter_fields = {
        'title': 'title',
        'tagline': 'tagline',
        'doi': 'doi',
        'authors': 'authors',
    }
    # nested_filter_fields = {
    #     'vote_type': {
    #         'field': 'votes',
    #         'path': 'votes.vote_type',
    #     },
    # }

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
        'tagline': {
            'options': {
                'pre_tags': ["<b>"],
                'post_tags': ["</b>"],
            },
        },
    }

    suggester_fields = {
        'title_suggest': {
            'field': 'title.suggest',
            'suggesters': [
                SUGGESTER_COMPLETION,
                SUGGESTER_TERM,
                SUGGESTER_PHRASE,
            ],
        }
    }
