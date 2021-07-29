from rest_framework.generics import ListAPIView
from search.views.paper import PaperDocumentView
from utils.permissions import ReadOnly
from rest_framework.response import Response
from elasticsearch_dsl import Search
import json

from search.serializers.combined import CombinedSerializer
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
)
from search.backends.multi_match_filter import MultiMatchSearchFilterBackend


class CombinedView(ListAPIView):
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
    # self.paper_search = Search(index=['paper'])

    self.paper_view = PaperDocumentView(*args, **kwargs)
    super(CombinedView, self).__init__(*args, **kwargs)

  def get_queryset(self):
    return

  def list(self, request, *args, **kwargs):
    response = {
      "papers": None
    }

    papers_raw = self.paper_view.filter_queryset(
        request,
    )

    response['papers'] = self.get_serializer(papers_raw, many=True)
    # print(json.dumps(response).data)
    return Response()

