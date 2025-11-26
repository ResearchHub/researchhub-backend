"""
Utility functions for handling search errors and logging.
"""

import logging
from typing import Any

import utils.sentry as sentry

logger = logging.getLogger(__name__)


def log_first_hit_index(response) -> None:
    """Log the index of the first hit if results are available."""
    if response.hits.total.value > 0:
        first_hit_index = response.hits[0].meta.index if response.hits else "N/A"
        logger.info(f"First hit index: {first_hit_index}")


def extract_opensearch_error_details(exception: Exception) -> dict[str, Any]:
    """Extract OpenSearch-specific error details from exception."""
    details = {}
    if hasattr(exception, "info"):
        details["info"] = str(exception.info)
    if hasattr(exception, "status_code"):
        details["status_code"] = exception.status_code
    if hasattr(exception, "error"):
        details["error"] = str(exception.error)
    if hasattr(exception, "message"):
        details["message"] = str(exception.message)
    return details


def categorize_error(exception_type: str, exception_message: str) -> str:
    """Categorize error based on exception type and message."""
    message_lower = exception_message.lower()
    if "timeout" in message_lower or "Timeout" in exception_type:
        return "timeout"
    if "connection" in message_lower or "Connection" in exception_type:
        return "connection"
    if "NotFound" in exception_type:
        return "not_found"
    return "unknown"


def handle_search_error(
    exception: Exception,
    query: str,
    offset: int,
    limit: int,
    sort: str,
) -> None:
    """Handle and log search errors with enhanced details."""
    exception_type = type(exception).__name__
    exception_message = str(exception)
    opensearch_details = extract_opensearch_error_details(exception)
    error_category = categorize_error(exception_type, exception_message)

    opensearch_suffix = (
        f", opensearch_details={opensearch_details}" if opensearch_details else ""
    )
    logger.error(
        "Document search failed - "
        f"query='{query}', "
        f"offset={offset}, "
        f"limit={limit}, "
        f"sort={sort}, "
        f"exception_type={exception_type}, "
        f"exception_message={exception_message}, "
        f"error_category={error_category}" + opensearch_suffix,
        exc_info=True,
    )


def log_search_error(
    exception: Exception,
    query: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    sort: str | None = None,
) -> None:
    """Log search view errors with enhanced details and Sentry integration.

    This function is designed to be exception-safe - if any part of the
    error handling fails, it will still attempt to log basic information.

    Args:
        exception: The exception that occurred
        query: Optional search query string
        page: Optional page number
        page_size: Optional page size
        sort: Optional sort option
    """
    try:
        exception_type = type(exception).__name__
        exception_message = str(exception)
    except Exception:
        exception_type = "UnknownException"
        exception_message = "Failed to extract exception details"

    try:
        opensearch_details = extract_opensearch_error_details(exception)
    except Exception:
        opensearch_details = {}

    try:
        opensearch_suffix = (
            f", opensearch_details={opensearch_details}" if opensearch_details else ""
        )
    except Exception:
        opensearch_suffix = ""

    try:
        log_message = (
            "Unified search error - "
            f"query='{query}', "
            f"page={page}, "
            f"page_size={page_size}, "
            f"sort={sort}, "
            f"exception_type={exception_type}, "
            f"exception_message={exception_message}" + opensearch_suffix
        )
        logger.error(log_message, exc_info=True)
    except Exception as log_error:
        try:
            logger.error(
                f"Unified search error - Failed to format log message: {log_error}",
                exc_info=True,
            )
        except Exception:
            pass

    try:
        sentry_data = {
            "query": query,
            "page": page,
            "page_size": page_size,
            "sort": sort,
            "exception_type": exception_type,
        }
        if opensearch_details:
            sentry_data["opensearch_details"] = opensearch_details
        sentry.log_error(
            exception,
            message=f"Unified search error: {exception_type}",
            json_data=sentry_data,
        )
    except Exception as sentry_error:
        try:
            logger.error(
                f"Failed to log search error to Sentry: {sentry_error}",
                exc_info=True,
            )
        except Exception:
            pass
