from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    MultiMatchSearchFilterBackend,
    FacetedSearchFilterBackend,
)

from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.documents.person import PersonDocument
from search.serializers.person import PersonDocumentSerializer
from utils.permissions import ReadOnly


class PersonDocumentView(DocumentViewSet):
    document = PersonDocument
    permission_classes = [ReadOnly]
    serializer_class = PersonDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
        DefaultOrderingFilterBackend,
        FacetedSearchFilterBackend,
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
        'fuzziness': 1,
    }

    faceted_search_fields = {
        'person_types': 'person_types'
    }

    post_filter_fields = {
        'person_types': 'person_types'
    }    
