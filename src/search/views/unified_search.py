"""
Unified search view for searching across documents and people.
"""

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from search.serializers.search import UnifiedSearchResultSerializer
from search.services.unified_search_service import UnifiedSearchService

logger = logging.getLogger(__name__)


class UnifiedSearchView(APIView):
    """
    Unified search endpoint for searching across all content types.

    GET /api/search/?q=<query>&page=<page>&page_size=<size>&sort=<sort>

    Query Parameters:
        - q (required): Search query string
        - page (optional): Page number, default=1
        - page_size (optional): Number of results per page, default=10, max=100
        - sort (optional): Sort option - relevance (default), newest, hot, upvoted

    Returns:
        Unified search results with separate sections for documents and people,
        plus aggregations for filtering.
    """

    permission_classes = [AllowAny]
    search_service = UnifiedSearchService()

    def get(self, request):
        """
        Handle GET request for unified search.
        """
        # Get and validate query parameter
        query = request.query_params.get("q", "").strip()
        if not query:
            return Response(
                {"error": "Query parameter 'q' is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get pagination parameters
        try:
            page = int(request.query_params.get("page", 1))
            if page < 1:
                page = 1
        except (TypeError, ValueError):
            page = 1

        try:
            page_size = int(request.query_params.get("page_size", 10))
            # Enforce reasonable limits
            if page_size < 1:
                page_size = 10
            elif page_size > 100:
                page_size = 100
        except (TypeError, ValueError):
            page_size = 10

        # Get sort parameter
        sort = request.query_params.get("sort", "relevance").lower()

        # Validate sort parameter
        valid_sorts = UnifiedSearchService.VALID_SORT_OPTIONS
        if sort not in valid_sorts:
            valid_sorts_str = ", ".join(valid_sorts)
            return Response(
                {
                    "error": (
                        f"Invalid sort parameter. " f"Must be one of: {valid_sorts_str}"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Perform search
        try:
            results = self.search_service.search(
                query=query,
                page=page,
                page_size=page_size,
                sort=sort,
            )

            # Serialize and return results
            serializer = UnifiedSearchResultSerializer(results)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Unified search error: {str(e)}", exc_info=True)
            return Response(
                {"error": "An error occurred while processing your search"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
