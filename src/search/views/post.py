from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    FacetedSearchFilterBackend,
    FilteringFilterBackend,
    HighlightBackend,
    OrderingFilterBackend,
    PostFilterFilteringFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.post import PostDocument
from search.serializers.post import PostDocumentSerializer
from utils.permissions import ReadOnly

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend

class PostDocumentView(DocumentViewSet):
    document = PostDocument
    permission_classes = [ReadOnly]
    serializer_class = PostDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    score_field = 'score'
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
        'title': {'boost': 2},
        'renderable_text': {'boost': 1},
        'hubs_flat': {'boost': 1},
    }

    multi_match_search_fields = {
        'title': {'boost': 2},
        'renderable_text': {'boost': 1},
        'authors.full_name': {'boost': 1},
        'hubs_flat': {'boost': 1},
        'hubs_flat': {'boost': 1},
    }

    multi_match_options = {
        'operator': 'and',
        'type': 'cross_fields',
        'analyzer': 'content_analyzer',
    }

    post_filter_fields = {
        'hubs': 'hubs.name',
    }

    faceted_search_fields = {
        'hubs': 'hubs.name'
    }

    filter_fields = {
        'publish_date': 'created_date'
    }

    ordering = ('_score', '-hot_score', '-discussion_count', '-created_date')

    ordering_fields = {
        'publish_date': 'created_date',
        'discussion_count': 'discussion_count',
        'score': 'score',
        'hot_score': 'hot_score',
    }

    highlight_fields = {
        'title': {
            'enabled': True,
            'options': {
                'pre_tags': ["<mark>"],
                'post_tags': ["</mark>"],
                'fragment_size': 2000,
                'number_of_fragments': 1,
            },
        },
        'renderable_text': {
            'enabled': True,
            'options': {
                'pre_tags': ["<mark>"],
                'post_tags': ["</mark>"],
                'fragment_size': 5000,
                'number_of_fragments': 1,
            },
        }
    }

    def __init__(self, *args, **kwargs):
        self.search = Search(index=['post'])
        super(PostDocumentView, self).__init__(*args, **kwargs)    

    def _filter_queryset(self, request):
        queryset = self.search

        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
            request,
            queryset,
            self,
        )

        return queryset