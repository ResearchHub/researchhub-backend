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
    SearchFilterBackend
)

from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.documents.paper import PaperDocument
from search.serializers.paper import PaperDocumentSerializer
from utils.permissions import ReadOnly
import re

class PaperDocumentView(DocumentViewSet):
    document = PaperDocument
    permission_classes = [ReadOnly]
    serializer_class = PaperDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    filter_backends = [
      CompoundSearchFilterBackend,
      FacetedSearchFilterBackend,
      FilteringFilterBackend,
      PostFilterFilteringFilterBackend,
      OrderingFilterBackend,
      HighlightBackend,
    ]

    search_fields = {
        'doi': {'boost': 3, 'fuzziness': 0},
        'title': {'boost': 2, 'fuzziness': 1},
        'raw_authors.full_name': {'boost': 1, 'fuzziness': 1},
        'abstract': {'boost': 1, 'fuzziness': 1},
        'hubs_flat': {'boost': 1, 'fuzziness': 1},
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
                'fragment_size': 1000,
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

    def get_queryset(self, **kwargs):
        query = self.request.query_params.get('search')
        doi_regex = '(10[.][0-9]{4,}(?:[.][0-9]+)*/(?:(?![%"#? ])\\S)+)'

        # If DOI is detexted, we want to override the configured queries
        # and insead, execute a single DOI query
        if re.match(doi_regex, query):
            self.search_fields = {
                'doi': {'boost': 3, 'fuzziness': 0}
            }

        return super().get_queryset(**kwargs)