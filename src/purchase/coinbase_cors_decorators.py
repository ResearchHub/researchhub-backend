import logging
import re
from functools import wraps
from typing import List

from django.conf import settings
from django.http import JsonResponse
from rest_framework import status

logger = logging.getLogger(__name__)


def get_approved_web_origins() -> List[str]:
    """Get approved web origins from Django CORS settings."""
    return getattr(settings, "CORS_ORIGIN_WHITELIST", [])


def is_origin_allowed_by_regex(origin: str) -> bool:
    """Check if origin matches any of the allowed regex patterns."""
    allowed_regexes = getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", [])
    for regex_pattern in allowed_regexes:
        if re.match(regex_pattern, origin):
            return True
    return False


def is_origin_approved(origin: str) -> bool:
    """Check if origin is approved via whitelist or regex patterns."""
    if not origin:
        return False

    # Check whitelist
    approved_origins = get_approved_web_origins()
    if origin in approved_origins:
        return True

    # Check regex patterns
    return is_origin_allowed_by_regex(origin)


def create_cors_preflight_response(origin: str) -> JsonResponse:
    response = JsonResponse({"detail": "CORS preflight check passed"})
    response["Access-Control-Allow-Origin"] = origin
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


def create_forbidden_response(message: str) -> JsonResponse:
    return JsonResponse({"error": message}, status=status.HTTP_403_FORBIDDEN)


def add_cors_headers_to_response(response, origin: str):
    response["Access-Control-Allow-Origin"] = origin
    return response


def secure_coinbase_cors(view_func):
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        origin = request.META.get("HTTP_ORIGIN", "")

        if request.method == "OPTIONS":
            return handle_preflight_request(origin)

        if request.method == "POST":
            forbidden_response = validate_post_request(origin)
            if forbidden_response:
                return forbidden_response

        response = view_func(self, request, *args, **kwargs)

        return finalize_response(response, origin)

    return wrapper


def handle_preflight_request(origin: str) -> JsonResponse:
    if is_origin_approved(origin):
        return create_cors_preflight_response(origin)

    logger.warning(f"Unauthorized CORS preflight attempt from origin: {origin}")
    return create_forbidden_response("Origin not allowed")


def validate_post_request(origin: str) -> JsonResponse:
    if not origin:
        logger.warning("Request without origin header - blocked")
        return create_forbidden_response("Origin header required")

    if not is_origin_approved(origin):
        logger.warning(f"Blocked unauthorized request from origin: {origin}")
        return create_forbidden_response("Origin not allowed")

    return None


def finalize_response(response, origin: str):
    if is_origin_approved(origin):
        logger.info(f"Added CORS headers for approved origin: {origin}")
        return add_cors_headers_to_response(response, origin)

    return response
