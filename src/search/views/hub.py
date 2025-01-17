from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.hub import HubDocument
from search.serializers.hub import HubDocumentSerializer
from user.views.follow_view_mixins import FollowViewActionMixin
from utils.permissions import ReadOnly


class HubDocumentView(FollowViewActionMixin, DocumentViewSet):
    document = HubDocument
    permission_classes = [ReadOnly]
    serializer_class = HubDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
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

    def __init__(self, *args, **kwargs):
        self.search = Search(index=["hub"])
        super(HubDocumentView, self).__init__(*args, **kwargs)

    def _filter_queryset(self, request):
        queryset = self.search

        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
                request,
                queryset,
                self,
            )

        return queryset
