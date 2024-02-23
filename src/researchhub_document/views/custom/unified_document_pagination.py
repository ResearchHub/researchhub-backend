from collections import OrderedDict

from django.db import connection
from django.core.paginator import Paginator
from django.utils.functional import cached_property
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

UNIFIED_DOC_PAGE_SIZE = 20

class PaginatorWithApproximateCount(Paginator):
    """
    Adapted from: https://gist.github.com/noviluni/d86adfa24843c7b8ed10c183a9df2afe
    """
    @cached_property
    def count(self):
        """
        Returns an approximate number of objects, across all pages.
        """
        try:
            with connection.cursor() as cursor:
                # Obtain estimated values
                # reltuples is a cached value that approximates the number of rows in the table
                cursor.execute(
                    "SELECT reltuples FROM pg_class WHERE relname = %s",
                    [self.object_list.query.model._meta.db_table]
                )
                estimate = int(cursor.fetchone()[0])
                return estimate
        except Exception:
            # If any other exception occurred fall back to default behaviour
            pass

        # We can fallback to a very large number,
        # because if Django receives a page number over the actual number of pages,
        # it will default to the last page.
        return 9999999999


class UnifiedDocPagination(PageNumberPagination):
    # We use a custom paginator to get an approximate count,
    # because the unified document table is very large
    # so the COUNT(*) ends up being very slow.
    # Also, we don't show an exact page count to the user,
    # we mainly use pagination to go to the next page.
    django_paginator_class = PaginatorWithApproximateCount
    page_size_query_param = "page_limit"
    max_page_size = 200  # NOTE: arbitrary size for security
    page_size = UNIFIED_DOC_PAGE_SIZE

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", self.page.paginator.count),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )
