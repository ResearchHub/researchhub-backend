from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    OrderingFilterBackend,
    FacetedSearchFilterBackend,
    PostFilterFilteringFilterBackend,
)
from elasticsearch_dsl import Search
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.person import PersonDocument
from search.serializers.person import PersonDocumentSerializer
from utils.permissions import ReadOnly


class PersonDocumentView(DocumentViewSet):
    document = PersonDocument
    permission_classes = [ReadOnly]
    serializer_class = PersonDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    # This field will be added to the ES _score
    score_field = 'user_reputation'
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
        FacetedSearchFilterBackend,
        PostFilterFilteringFilterBackend,
        DefaultOrderingFilterBackend,
        OrderingFilterBackend,
    ]

    search_fields = {
        'full_name': {'boost': 2, 'fuzziness': 1},
        'description': {'boost': 1, 'fuzziness': 1},
        'headline.title': {'boost': 1, 'fuzziness': 1},
    }

    multi_match_search_fields = {
        'full_name': {'boost': 2},
        'description': {'boost': 1},
        'headline.title': {'boost': 1},
    }

    multi_match_options = {
        'operator': 'and',
        'type': 'cross_fields',
        'analyzer': 'standard',
    }

    faceted_search_fields = {
        'person_types': 'person_types'
    }

    post_filter_fields = {
        'person_types': 'person_types'
    }    

    ordering_fields = {
        'author_score': 'author_score',
        'user_reputation': 'user_reputation',
    }    

    def __init__(self, *args, **kwargs):
        self.search = Search(index=['person'])
        super(PersonDocumentView, self).__init__(*args, **kwargs)    

    def _filter_queryset(self, request):
        queryset = self.search

        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
            request,
            queryset,
            self,
        )

        return queryset