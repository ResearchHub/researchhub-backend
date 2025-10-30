"""
Utility functions for AWS Personalize item data export.
"""

import re
from functools import wraps
from typing import Optional

from django.conf import settings
from django.db import connection

from analytics.constants.personalize_constants import MAX_TEXT_LENGTH


def assert_no_queries(func):
    """Decorator to assert function makes zero queries (DEBUG only)."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not settings.DEBUG:
            return func(*args, **kwargs)

        query_count_before = len(connection.queries)
        result = func(*args, **kwargs)
        query_count_after = len(connection.queries)
        new_queries = query_count_after - query_count_before

        if new_queries > 0:
            recent = connection.queries[query_count_before:query_count_after]
            raise AssertionError(
                f"{func.__name__} made {new_queries} unexpected queries!\n"
                f"Queries: {[q['sql'][:100] for q in recent]}"
            )

        return result

    return wrapper


def clean_text_for_csv(text: Optional[str]) -> Optional[str]:
    """
    Prepare text for CSV export.

    Strips HTML tags and truncates to maximum length.
    CSV module handles quotes, newlines, and special characters automatically.
    """
    if not text:
        return None

    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip()

    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    return text if text else None
