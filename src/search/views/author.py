from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    MultiMatchSearchFilterBackend
)

from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.documents.author import AuthorDocument
from search.serializers.author import AuthorDocumentSerializer
from utils.permissions import ReadOnly


class AuthorDocumentView(DocumentViewSet):
    document = AuthorDocument
    permission_classes = [ReadOnly]
    serializer_class = AuthorDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
        DefaultOrderingFilterBackend,
    ]

    search_fields = {
        'full_name': {'boost': 2, 'fuzziness': 1},
        'description': {'boost': 1, 'fuzziness': 1},
        'headline': {'boost': 1, 'fuzziness': 1},
        'university.name': {'boost': 1, 'fuzziness': 1},
        'university.city': {'boost': 1, 'fuzziness': 1},
        'university.country': {'boost': 1, 'fuzziness': 1},
        'university.state': {'boost': 1, 'fuzziness': 1},
    }

    multi_match_search_fields = {
        'full_name': {'boost': 2},
        'description': {'boost': 1},
        'headline': {'boost': 1},
        'university.name': {'boost': 1},
        'university.city': {'boost': 1},
        'university.country': {'boost': 1},
        'university.state': {'boost': 1},
    }

    multi_match_options = {
        'operator': 'and',
        'fuzziness': 1,
    }
