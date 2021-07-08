from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    HighlightBackend,
    FilteringFilterBackend,
    NestedFilteringFilterBackend,
    IdsFilterBackend,
    OrderingFilterBackend,
    SuggesterFilterBackend,
    PostFilterFilteringFilterBackend,
    FacetedSearchFilterBackend,
    SearchFilterBackend,
)

from elasticsearch_dsl.query import Q

from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.documents.paper import PaperDocument
from search.serializers.paper import PaperDocumentSerializer
from utils.permissions import ReadOnly

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend

class PaperDocumentView(DocumentViewSet):
    document = PaperDocument
    permission_classes = [ReadOnly]
    serializer_class = PaperDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
        FacetedSearchFilterBackend,
        FilteringFilterBackend,
        PostFilterFilteringFilterBackend,
        DefaultOrderingFilterBackend,
        OrderingFilterBackend,
        HighlightBackend,
    ]

    search_fields = {
        'doi': {'boost': 3, 'fuzziness': 1},
        'title': {'boost': 2, 'fuzziness': 1},
        'raw_authors.full_name': {'boost': 1, 'fuzziness': 1},
        'abstract': {'boost': 1, 'fuzziness': 1},
        'hubs_flat': {'boost': 1, 'fuzziness': 1},
    }

    multi_match_search_fields = {
        'doi': {'boost': 3, 'fuzziness': 1},
        'title': {'boost': 2, 'fuzziness': 1},
        'raw_authors.full_name': {'boost': 1, 'fuzziness': 1},
        'abstract': {'boost': 1, 'fuzziness': 1},
        'hubs_flat': {'boost': 1, 'fuzziness': 1},
    }

    multi_match_options = {
        'operator': 'and',
        'type': 'best_fields',
    }

    post_filter_fields = {
        'hubs': 'hubs.name',
    }

    faceted_search_fields = {
        'hubs': 'hubs.name'
    }

    filter_fields = {
        'publish_date': 'paper_publish_date'
    }

    ordering = ('_score', '-hot_score', '-discussion_count', '-paper_publish_date')

    ordering_fields = {
        'publish_date': 'paper_publish_date',
        'discussion_count': 'discussion_count',
        'score': 'score',
        'hot_score': 'hot_score',
    }

    highlight_fields = {
        'raw_authors.full_name': {
            'field': 'raw_authors',
            'enabled': True,
            'options': {
                'pre_tags': ["<mark>"],
                'post_tags': ["</mark>"],
                'fragment_size': 1000,
                'number_of_fragments': 10,
            },
        },
        'title': {
            'enabled': True,
            'options': {
                'pre_tags': ["<mark>"],
                'post_tags': ["</mark>"],
                'fragment_size': 2000,
                'number_of_fragments': 1,
            },
        },
        'abstract': {
            'enabled': True,
            'options': {
                'pre_tags': ["<mark>"],
                'post_tags': ["</mark>"],
                'fragment_size': 5000,
                'number_of_fragments': 1,
            },
        }
    }

