from elasticsearch_dsl import Search
from rest_framework.response import Response
from rest_framework.views import APIView

from search.documents.hub import HubDocument
from search.documents.paper import PaperDocument
from search.documents.post import PostDocument
from search.documents.user import UserDocument
from search.serializers.combined import CombinedSerializer
from search.serializers.hub import HubDocumentSerializer
from search.serializers.paper import PaperDocumentSerializer
from search.serializers.post import PostDocumentSerializer
from search.serializers.user import UserDocumentSerializer
from utils.permissions import ReadOnly


class CombinedSuggestView(APIView):
    permission_classes = [ReadOnly]
    serializer_class = CombinedSerializer

    def get(self, request, *args, **kwargs):
        # Retrieve the query from the request
        query = request.query_params.get("query", "")
        suggestion_types = [
            {
                "serializer": PaperDocumentSerializer,
                "document": PaperDocument,
                "suggester_field": "title_suggest",
            },
            {
                "serializer": PostDocumentSerializer,
                "document": PostDocument,
                "suggester_field": "title_suggest",
            },
            {
                "serializer": UserDocumentSerializer,
                "document": UserDocument,
                "suggester_field": "full_name_suggest",
            },
            {
                "serializer": HubDocumentSerializer,
                "document": HubDocument,
                "suggester_field": "name_suggest",
            },
        ]

        combined_suggestions = []  # Combined suggestions from different suggesters
        for suggestion_type in suggestion_types:
            s = Search(index=suggestion_type["document"]._index._name)
            s = s.suggest(
                "suggestions",
                query,
                completion={"field": suggestion_type["suggester_field"]},
            )
            es_response = s.execute().suggest.to_dict()

            for suggestion_with_metadata in es_response["suggestions"]:
                combined_suggestions.extend(suggestion_with_metadata["options"][:10])

        return Response(combined_suggestions)
