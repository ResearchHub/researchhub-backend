from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    HighlightBackend,
    FilteringFilterBackend,
    NestedFilteringFilterBackend,
    IdsFilterBackend,
    OrderingFilterBackend,
    SuggesterFilterBackend,
    MultiMatchSearchFilterBackend,
    PostFilterFilteringFilterBackend,
    FacetedSearchFilterBackend
)
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.documents.paper import PaperDocument
from search.serializers.paper import PaperDocumentSerializer
from utils.permissions import ReadOnly

class PaperDocumentView(DocumentViewSet):
    document = PaperDocument
    permission_classes = [ReadOnly]
    serializer_class = PaperDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    filter_backends = [
      MultiMatchSearchFilterBackend,
      HighlightBackend,
      CompoundSearchFilterBackend,
      FacetedSearchFilterBackend,
      FilteringFilterBackend,
      PostFilterFilteringFilterBackend,
      OrderingFilterBackend,
    ]

    search_fields = [
        'title',
        'doi',
        'authors',
    ]

    multi_match_search_fields = {
        'doi': {'boost': 4},
        'title': {'boost': 3},
        'authors': {'boost': 2},
        'abstract': {'boost': 1},
    }

    post_filter_fields = {
      'hubs': 'hubs',
    }

    faceted_search_fields = {
      'hubs': 'hubs'
    }

    filter_fields = {
      'publish_date': 'paper_publish_date'
    }

    ordering_fields = {
      'publish_date': 'paper_publish_date'
    }

    highlight_fields = {
        'title': {
            'options': {
                'pre_tags': ["<em>"],
                'post_tags': ["</em>"],
            },
        }
    }
