"""
Unified search view for searching across documents (papers/posts).
"""

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from search.serializers.search import (
    UnifiedSearchRequestSerializer,
    UnifiedSearchResultSerializer,
)
from search.services.search_error_utils import log_search_error
from search.services.unified_search_service import UnifiedSearchService

logger = logging.getLogger(__name__)


class UnifiedSearchView(APIView):
    """
    Unified search endpoint for searching across documents (papers/posts).

    GET /api/search/?q=<query>&page=<page>&page_size=<size>&sort=<sort>

    Query Parameters:
        - q (required): Search query string
        - page (optional): Page number, default=1
        - page_size (optional): Number of results per page, default=10, max=100
        - sort (optional): Sort option - relevance (default), newest

    Returns:
        Unified search results with documents (papers and posts).
    """

    permission_classes = [AllowAny]
    search_service = UnifiedSearchService()

    def get(self, request):
        """
        Handle GET request for unified search.
        """
        # Validate request data
        serializer = UnifiedSearchRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        # Get validated data
        query = serializer.validated_data["q"]
        page = serializer.validated_data["page"]
        page_size = serializer.validated_data["page_size"]
        sort = serializer.validated_data["sort"]

        # Perform search
        try:
            results = self.search_service.search(
                query=query,
                page=page,
                page_size=page_size,
                sort=sort,
                request=request,
            )

            # Serialize and return results
            result_serializer = UnifiedSearchResultSerializer(results)
            return Response(result_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            log_search_error(e, query=query, page=page, page_size=page_size, sort=sort)
            return Response(
                {"error": "An error occurred while processing your search"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
