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
    MultiMatchSearchFilterBackend,
    SearchFilterBackend,
)

from django_elasticsearch_dsl_drf import (
    constants
)

from django_elasticsearch_dsl_drf.filter_backends.search.query_backends import (
    MatchPhrasePrefixQueryBackend,
    NestedQueryBackend,
    BaseSearchQueryBackend,
    MultiMatchQueryBackend,

)

from django_elasticsearch_dsl_drf.filter_backends.search import (
    BaseSearchFilterBackend

)
from elasticsearch_dsl.query import Q

from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.documents.paper import PaperDocument
from search.serializers.paper import PaperDocumentSerializer
from utils.permissions import ReadOnly
import re



class MatchPhraseQueryBackend(BaseSearchQueryBackend):
    matching = 'should'

    @classmethod
    def construct_search(cls, request, view, search_backend):

        field = 'title'
        __queries = []
        __queries.append(
            # Q('term', **{field: 'stdp'})
            Q('match', **{field: 'stdp'}    )
        )
        return __queries

class PhraseSearchFilterBackend(BaseSearchFilterBackend):
    matching = 'should'
    query_backends = [
        MatchPhraseQueryBackend,
    ]


class PaperDocumentView(DocumentViewSet):
    document = PaperDocument
    permission_classes = [ReadOnly]
    serializer_class = PaperDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    filter_backends = [
        # PhraseSearchFilterBackend,
        # MultiMatchSearchFilterBackend,
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
        'operator': 'and'
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


    # def get_queryset(self, **kwargs):
    #     gen_query = super().get_queryset(**kwargs)

    #     query = self.request.query_params.get('search')
    #     doi_regex = '(10[.][0-9]{4,}(?:[.][0-9]+)*/(?:(?![%"#? ])\\S)+)'

    #     # If DOI is detexted, we want to override the configured queries
    #     # and insead, execute a single DOI query
    #     if re.match(doi_regex, query):
    #         self.search_fields = {
    #             'doi': {'boost': 3, 'fuzziness': 0}
    #         }
    #         self.multi_match_search_fields = {
    #             'doi': {'boost': 3, 'fuzziness': 0}
    #         }            

    #     return gen_query
