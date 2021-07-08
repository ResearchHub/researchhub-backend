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
    MultiMatchSearchFilterBackend
)

from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination

from search.documents.hub import HubDocument
from search.serializers.hub import HubDocumentSerializer
from utils.permissions import ReadOnly


class HubDocumentView(DocumentViewSet):
    document = HubDocument
    permission_classes = [ReadOnly]
    serializer_class = HubDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = 'id'
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
        DefaultOrderingFilterBackend,
    ]

    search_fields = {
        'name': {'boost': 1, 'fuzziness': 1},
        'acronym': {'boost': 1, 'fuzziness': 1},
    }

    multi_match_search_fields = {
        'name': {'boost': 1, 'fuzziness': 1},
        'acronym': {'boost': 1, 'fuzziness': 1},
    }

    multi_match_options = {
        'operator': 'and',
    }
