import logging
import re
from functools import wraps
from typing import List

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from rest_framework import status

logger = logging.getLogger(__name__)

MOBILE_BROWSER_INDICATORS = [
    "mobile",
    "android",
    "iphone",
    "ipad",
    "ipod",
    "blackberry",
    "windows phone",
    "opera mini",
    "opera mobi",
]


def is_mobile_browser_request(request: HttpRequest) -> bool:
    origin = request.META.get("HTTP_ORIGIN", "")
    user_agent = request.META.get("HTTP_USER_AGENT", "").lower()

    return not origin or any(
        indicator in user_agent for indicator in MOBILE_BROWSER_INDICATORS
    )


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
    response = JsonResponse({"detail": "Web CORS preflight check passed"})
    response["Access-Control-Allow-Origin"] = origin
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


def create_mobile_preflight_response() -> JsonResponse:
    return JsonResponse({"detail": "Mobile preflight check passed"})


def create_forbidden_response(message: str) -> JsonResponse:
    return JsonResponse({"error": message}, status=status.HTTP_403_FORBIDDEN)


def add_cors_headers_to_response(response, origin: str):
    response["Access-Control-Allow-Origin"] = origin
    return response


def secure_coinbase_cors(view_func):
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        origin = request.META.get("HTTP_ORIGIN", "")
        is_mobile_request = is_mobile_browser_request(request)

        if request.method == "OPTIONS":
            return handle_preflight_request(is_mobile_request, origin)

        if request.method == "POST":
            forbidden_response = validate_post_request(is_mobile_request, origin)
            if forbidden_response:
                return forbidden_response

        response = view_func(self, request, *args, **kwargs)

        return finalize_response(response, is_mobile_request, origin)

    return wrapper


def handle_preflight_request(is_mobile_request: bool, origin: str) -> JsonResponse:
    if is_mobile_request:
        logger.info("Mobile app preflight request - no CORS headers returned")
        return create_mobile_preflight_response()

    if is_origin_approved(origin):
        return create_cors_preflight_response(origin)

    logger.warning(f"Unauthorized web CORS preflight attempt from origin: {origin}")
    return create_forbidden_response("Origin not allowed for web clients")


def validate_post_request(is_mobile_request: bool, origin: str) -> JsonResponse:
    if is_mobile_request:
        logger.info("Mobile app request - proceeding without CORS validation")
        return None

    if not origin:
        logger.warning("Web request without origin header - blocked")
        return create_forbidden_response("Origin header required for web clients")

    if not is_origin_approved(origin):
        logger.warning(f"Blocked unauthorized web request from origin: {origin}")
        return create_forbidden_response("Origin not allowed for web clients")

    return None


def finalize_response(response, is_mobile_request: bool, origin: str):
    if is_mobile_request:
        logger.info("Mobile app response - no CORS headers added (compliance)")
        return response

    if is_origin_approved(origin):
        logger.info(f"Added CORS headers for approved web origin: {origin}")
        return add_cors_headers_to_response(response, origin)

    return response
