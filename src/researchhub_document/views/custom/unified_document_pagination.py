from collections import OrderedDict

from django.core.paginator import InvalidPage
from django.db import connection
from rest_framework.exceptions import NotFound
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

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate a queryset if required, either returning a
        page object, or `None` if pagination is not configured for this view.
        """
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = self.get_page_number(request, paginator)

        try:
            self.page = paginator.page(page_number)
        except InvalidPage as exc:
            msg = self.invalid_page_message.format(
                page_number=page_number, message=str(exc)
            )
            raise NotFound(msg)

        if paginator.num_pages > 1 and self.template is not None:
            # The browsable API should display pagination controls.
            self.display_page_controls = True

        self.request = request
        return list(self.page)
