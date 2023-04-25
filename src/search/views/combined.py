from django_elasticsearch_dsl_drf.constants import SUGGESTER_COMPLETION
from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    FacetedSearchFilterBackend,
    FilteringFilterBackend,
    HighlightBackend,
    IdsFilterBackend,
    NestedFilteringFilterBackend,
    OrderingFilterBackend,
    PostFilterFilteringFilterBackend,
    SearchFilterBackend,
    SuggesterFilterBackend,
)
from elasticsearch_dsl import Search
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.serializers.combined import CombinedSerializer
from search.views.hub import HubDocumentView
from search.views.paper import PaperDocumentView
from search.views.person import PersonDocumentView
from search.views.post import PostDocumentView
from utils.permissions import ReadOnly


class CombinedView(ListAPIView):
    max_results_per_entity = 2
    permission_classes = [ReadOnly]
    serializer_class = CombinedSerializer
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
        FacetedSearchFilterBackend,
        FilteringFilterBackend,
        PostFilterFilteringFilterBackend,
        DefaultOrderingFilterBackend,
        OrderingFilterBackend,
        HighlightBackend,
    ]

    def __init__(self, *args, **kwargs):
        self.paper_view = PaperDocumentView(*args, **kwargs)
        self.post_view = PostDocumentView(*args, **kwargs)
        self.person_view = PersonDocumentView(*args, **kwargs)
        self.hub_view = HubDocumentView(*args, **kwargs)
        super(CombinedView, self).__init__(*args, **kwargs)

    def get_queryset(self):
        return

    def list(self, request, *args, **kwargs):
        response = {
            "paper": [],
            "post": [],
            "person": [],
            "hub": [],
        }

        papers_es_res = self.paper_view._filter_queryset(
            request,
        )
        post_es_res = self.post_view._filter_queryset(
            request,
        )
        person_es_res = self.person_view._filter_queryset(
            request,
        )
        hub_es_res = self.hub_view._filter_queryset(
            request,
        )

        response["paper"] = self.get_serializer(papers_es_res, many=True).data[
            0 : self.max_results_per_entity
        ]
        response["post"] = self.get_serializer(post_es_res, many=True).data[
            0 : self.max_results_per_entity
        ]
        response["person"] = self.get_serializer(person_es_res, many=True).data[
            0 : self.max_results_per_entity
        ]
        response["hub"] = self.get_serializer(hub_es_res, many=True).data[
            0 : self.max_results_per_entity
        ]

        return Response(response)
