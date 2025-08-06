from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.base.filters import DefaultOrderingFilterBackend, SearchFilterBackend
from search.base.pagination import LimitOffsetPagination
from search.base.viewsets import ElasticsearchViewSet
from search.documents.journal import JournalDocument
from search.serializers.hub import HubDocumentSerializer
from utils.permissions import ReadOnly


class JournalDocumentView(ElasticsearchViewSet):
    document = JournalDocument
    permission_classes = [ReadOnly]
    serializer_class = HubDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        MultiMatchSearchFilterBackend,
        SearchFilterBackend,
        DefaultOrderingFilterBackend,
    ]

    search_fields = {
        "name": {"boost": 1, "fuzziness": 1},
        "acronym": {"boost": 1, "fuzziness": 1},
        "description": {"boost": 1, "fuzziness": 1},
    }

    multi_match_search_fields = {
        "name": {"boost": 1},
        "acronym": {"boost": 1},
        "description": {"boost": 1},
    }

    multi_match_options = {
        "operator": "and",
        "type": "cross_fields",
        "analyzer": "content_analyzer",
    }
