from elasticsearch_dsl import Search
from rest_framework.response import Response
from rest_framework.views import APIView

from search.documents.hub import HubDocument
from search.documents.paper import PaperDocument
from search.documents.post import PostDocument
from search.documents.user import UserDocument
from search.serializers.combined import CombinedSerializer
from utils.permissions import ReadOnly


class CombinedSuggestView(APIView):
    permission_classes = [ReadOnly]
    serializer_class = CombinedSerializer

    def get(self, request, *args, **kwargs):
        query = request.query_params.get("query", "")
        suggestion_types = [
            {
                "document": PaperDocument,
                "suggester_field": "title_suggest",
            },
            {
                "document": PostDocument,
                "suggester_field": "title_suggest",
            },
            {
                "document": UserDocument,
                "suggester_field": "full_name_suggest",
            },
            {
                "document": HubDocument,
                "suggester_field": "name_suggest",
            },
        ]

        combined_suggestions = []  # Combined suggestions from different suggesters
        for suggestion_type in suggestion_types:
            search = Search(index=suggestion_type["document"]._index._name)
            suggest = search.suggest(
                "suggestions",
                query,
                completion={"field": suggestion_type["suggester_field"]},
            )
            es_response = suggest.execute().suggest.to_dict()

            for suggestion_with_metadata in es_response["suggestions"]:
                combined_suggestions.extend(suggestion_with_metadata["options"][:3])

        return Response(combined_suggestions)
