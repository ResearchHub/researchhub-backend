from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.base.filters import (
    DefaultOrderingFilterBackend,
    FacetedSearchFilterBackend,
    OrderingFilterBackend,
    PostFilterFilteringFilterBackend,
    SearchFilterBackend,
)
from search.base.pagination import LimitOffsetPagination
from search.base.viewsets import ElasticsearchViewSet
from search.documents.person import PersonDocument
from search.serializers.person import PersonDocumentSerializer
from utils.permissions import ReadOnly


class PersonDocumentView(ElasticsearchViewSet):
    document = PersonDocument
    permission_classes = [ReadOnly]
    serializer_class = PersonDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    # This field will be added to the ES _score
    score_field = "user_reputation"
    filter_backends = [
        MultiMatchSearchFilterBackend,
        SearchFilterBackend,
        FacetedSearchFilterBackend,
        PostFilterFilteringFilterBackend,
        DefaultOrderingFilterBackend,
        OrderingFilterBackend,
    ]

    search_fields = {
        "full_name": {"boost": 2, "fuzziness": 1},
        "description": {"boost": 1, "fuzziness": 1},
        "headline": {"boost": 1, "fuzziness": 1},
    }

    multi_match_search_fields = {
        "full_name": {"boost": 2},
        "description": {"boost": 1},
        "headline": {"boost": 1},
    }

    multi_match_options = {
        "operator": "and",
        "type": "cross_fields",
        "analyzer": "content_analyzer",
    }

    faceted_search_fields = {"person_types": "person_types"}

    post_filter_fields = {"person_types": "person_types"}

    ordering_fields = {
        "author_score": "author_score",
        "user_reputation": "user_reputation",
    }

    def filter_queryset(self, queryset):
        """
        Apply filtering backends to the queryset.
        """
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
                request=self.request, queryset=queryset, view=self
            )
        return queryset
