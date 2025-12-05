"""
Unified search view for searching across documents (papers/posts).
"""

import logging
import re

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.exceptions import PermissionDenied

from search.serializers.search import (
    UnifiedSearchRequestSerializer,
    UnifiedSearchResultSerializer,
)
from search.services.search_error_utils import log_search_error
from search.services.unified_search_service import UnifiedSearchService
from utils.bot_detection import get_client_ip, validate_request_headers
from utils.pattern_detection import RequestPatternAnalyzer
from utils.search_throttles import (
    SearchAnonBurstThrottle,
    SearchAnonDailyThrottle,
    SearchAnonRateThrottle,
    SearchUserRateThrottle,
)

logger = logging.getLogger(__name__)

MAX_PAGE_NUMBER = 100

SUSPICIOUS_PATTERNS = [
    r"script[>\s]",
    r"eval\(",
    r"\$\{",
    r"\*{10,}",
]


def validate_query(query_string: str) -> tuple[bool, str]:
    if len(query_string) < 2:
        return False, "Query must be at least 2 characters"

    if len(query_string) > 200:
        return False, "Query cannot exceed 200 characters"

    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, query_string, re.IGNORECASE):
            return False, "Invalid query pattern detected"

    special_char_count = len(
        [c for c in query_string if not c.isalnum() and not c.isspace()]
    )
    special_char_ratio = special_char_count / len(query_string) if query_string else 0
    if special_char_ratio > 0.5:
        return False, "Query contains too many special characters"

    return True, ""


class UnifiedSearchView(APIView):
    """
    Unified search endpoint for searching across documents (papers/posts).

    GET /api/search/?q=<query>&page=<page>&page_size=<size>&sort=<sort>

    Query Parameters:
        - q (required): Search query string
        - page (optional): Page number, default=1, max=100
        - page_size (optional): Number of results per page, default=10, max=100
        - sort (optional): Sort option - relevance (default), newest

    Returns:
        Unified search results with documents (papers and posts).
    """

    permission_classes = [AllowAny]
    throttle_classes = [
        SearchAnonBurstThrottle,  # 5/second
        SearchAnonRateThrottle,  # 20/minute
        SearchAnonDailyThrottle,  # 500/day
        SearchUserRateThrottle,  # 100/minute (for authenticated users)
    ]
    search_service = UnifiedSearchService()

    def get(self, request):
        """
        Handle GET request for unified search.
        """
        ip = get_client_ip(request)

        try:
            validate_request_headers(request)
        except PermissionDenied as e:
            logger.warning(
                f"Bot detection blocked request from IP: {ip}, "
                f"Error: {str(e)}"
            )
            return Response(
                {"error": "Automated requests are not allowed"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Validate request data
        serializer = UnifiedSearchRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        # Get validated data
        query = serializer.validated_data["q"]
        page = serializer.validated_data["page"]
        page_size = serializer.validated_data["page_size"]
        sort = serializer.validated_data["sort"]

        if page > MAX_PAGE_NUMBER:
            logger.warning(
                f"Deep pagination attempt blocked: page={page} from IP: {ip}"
            )
            return Response(
                {
                    "error": f"Page number cannot exceed {MAX_PAGE_NUMBER}. "
                    "Use more specific search terms."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_valid, error_msg = validate_query(query)
        if not is_valid:
            logger.warning(
                f"Invalid query blocked from IP: {ip}, Error: {error_msg}"
            )
            return Response(
                {"error": error_msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pattern_analyzer = RequestPatternAnalyzer(ip)
        pattern_result = pattern_analyzer.record_request(query, page)

        if pattern_result["action"] == "block":
            issue_types = [issue.get("type", "unknown") for issue in pattern_result["issues"]]
            logger.warning(
                f"Pattern detection blocked request from IP: {ip}, "
                f"Issue types: {issue_types}, "
                f"Score: {pattern_result['score']:.2f}"
            )
            response = Response(
                {"error": "Suspicious activity detected. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = "60"
            return response

        if pattern_result["suspicious"] and pattern_result["action"] == "warn":
            issue_types = [issue.get("type", "unknown") for issue in pattern_result["issues"]]
            logger.info(
                f"Suspicious pattern detected (warn) from IP: {ip}, "
                f"Issue types: {issue_types}, "
                f"Score: {pattern_result['score']:.2f}"
            )

        try:
            results = self.search_service.search(
                query=query,
                page=page,
                page_size=page_size,
                sort=sort,
                request=request,
            )

            result_serializer = UnifiedSearchResultSerializer(results)
            return Response(result_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            log_search_error(e, query=query, page=page, page_size=page_size, sort=sort)
            logger.error(
                f"Search error from IP: {ip}, Error: {str(e)}"
            )
            return Response(
                {"error": "An error occurred while processing your search"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
