from collections import OrderedDict

from django.db import connection
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

UNIFIED_DOC_PAGE_SIZE = 20


class UnifiedDocPagination(PageNumberPagination):
    page_size_query_param = "page_limit"
    max_page_size = 200  # NOTE: arbitrary size for security
    page_size = UNIFIED_DOC_PAGE_SIZE

    def _get_estimated_count(self):
        cursor = connection.cursor()
        cursor.execute(
            "SELECT reltuples FROM pg_class WHERE relname = 'researchhub_document_researchhubunifieddocument'"
        )
        n = int(cursor.fetchone()[0])
        connection.close()
        return n

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", self._get_estimated_count()),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )
