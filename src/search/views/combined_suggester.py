# # from django_elasticsearch_dsl_drf.constants import SUGGESTER_COMPLETION
# # from django_elasticsearch_dsl_drf.filter_backends import (
# #     CompoundSearchFilterBackend,
# #     DefaultOrderingFilterBackend,
# #     FacetedSearchFilterBackend,
# #     FilteringFilterBackend,
# #     HighlightBackend,
# #     IdsFilterBackend,
# #     NestedFilteringFilterBackend,
# #     OrderingFilterBackend,
# #     PostFilterFilteringFilterBackend,
# #     SearchFilterBackend,
# #     SuggesterFilterBackend,
# # )
# # from elasticsearch_dsl import Search
# # from rest_framework.generics import ListAPIView
# # from rest_framework.response import Response
# # from search.views.paper_suggester import PaperSuggesterDocumentView
# # from search.views.post_suggester import PostSuggesterDocumentView
# # from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
# # from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
# # from search.views.hub import HubDocumentView
# # from search.views.paper import PaperDocumentView
# # from search.views.person import PersonDocumentView
# # from search.views.post import PostDocumentView
# # from search.serializers.combined import CombinedSerializer
# # from utils.permissions import ReadOnly
# # from elasticsearch import Elasticsearch
# # from django.http import JsonResponse


# class CombinedSuggestView(ListAPIView):
#     max_results_per_entity = 2
#     permission_classes = [ReadOnly]
#     serializer_class = CombinedSerializer
#     filter_backends = [
#         # MultiMatchSearchFilterBackend,
#         # CompoundSearchFilterBackend,
#         # FacetedSearchFilterBackend,
#         # FilteringFilterBackend,
#         # PostFilterFilteringFilterBackend,
#         # DefaultOrderingFilterBackend,
#         # OrderingFilterBackend,
#         # HighlightBackend,
#     ]

#     def __init__(self, *args, **kwargs):
#         self.paper_view = PaperSuggesterDocumentView(*args, **kwargs)
#         self.post_view = PostSuggesterDocumentView(*args, **kwargs)
#         # self.person_view = PersonDocumentView(*args, **kwargs)
#         # self.hub_view = HubDocumentView(*args, **kwargs)
#         super(CombinedSuggestView, self).__init__(*args, **kwargs)

#     def get_queryset(self):
#         return


#     def list(self, request, *args, **kwargs):
#         response = {
#             "paper": [],
#             "post": [],
#             # "person": [],
#             # "hub": [],
#         }

#         print('self.paper_view', self.paper_view)

#         papers_es_res = self.paper_view._filter_queryset(
#             request,
#         )
#         post_es_res = self.post_view._filter_queryset(
#             request,
#         )
#         # person_es_res = self.person_view._filter_queryset(
#         #     request,
#         # )
#         # hub_es_res = self.hub_view._filter_queryset(
#         #     request,
#         # )

#         response["paper"] = self.get_serializer(papers_es_res, many=True).data[
#             0 : self.max_results_per_entity
#         ]
#         response["post"] = self.get_serializer(post_es_res, many=True).data[
#             0 : self.max_results_per_entity
#         ]
#         # response["person"] = self.get_serializer(person_es_res, many=True).data[
#         #     0 : self.max_results_per_entity
#         # ]
#         # response["hub"] = self.get_serializer(hub_es_res, many=True).data[
#         #     0 : self.max_results_per_entity
#         # ]

#         return Response(response)


from elasticsearch_dsl import Search
from rest_framework.response import Response
from rest_framework.views import APIView

from search.documents.hub import HubDocument
from search.documents.paper import PaperDocument
from search.documents.person import PersonDocument
from search.documents.post import PostDocument
from search.serializers.combined import CombinedSerializer
from search.serializers.hub import HubDocumentSerializer
from search.serializers.paper import PaperDocumentSerializer
from search.serializers.person import PersonDocumentSerializer
from search.serializers.post import PostDocumentSerializer
from utils.permissions import ReadOnly


class CombinedSuggestView(APIView):
    permission_classes = [ReadOnly]
    serializer_class = CombinedSerializer

    def get(self, request, *args, **kwargs):
        # Retrieve the query from the request
        query = request.query_params.get("query", "")

        # Define the serializers for each type of document
        serializers = {
            "paper": PaperDocumentSerializer,
            "post": PostDocumentSerializer,
            # 'person': PersonDocumentSerializer,
            # 'hub': HubDocumentSerializer
        }

        # Initialize the response data structure
        response_data = {
            "papers": [],
            "posts": [],
            "people": [],
            # 'hubs': []
        }

        all_suggestions = []

        for doc_type, serializer in serializers.items():
            # Get the document class based on the doc_type
            document = globals()[f"{doc_type.capitalize()}Document"]

            s = Search(index=document._index._name)
            s = s.suggest("suggestions", query, completion={"field": "title_suggest"})
            es_response = s.execute().suggest.to_dict()

            for suggestion_with_metadata in es_response["suggestions"]:
                all_suggestions.extend(suggestion_with_metadata["options"][:2])

            # serializer_with_data = serializer(data=suggestions, many=True)
            # serializer_with_data.is_valid()

        return Response(all_suggestions)
