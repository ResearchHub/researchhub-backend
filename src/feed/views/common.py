"""
Common functionality shared between feed ViewSets.
"""

from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from researchhub.pagination import NoCountPaginator


class FeedPagination(PageNumberPagination):
    """
    Pagination class for feed endpoints.
    Optimized to skip expensive COUNT queries.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    django_paginator_class = NoCountPaginator

    def get_paginated_response(self, data):
        """
        Return paginated response without total count.
        Uses has_next to determine if there are more pages.
        """
        # FIXME: Only include next link if there are results equal to page size
        # to avoid repeated requests for empty pages
        next_link = None
        if data and len(data) == 0:
            next_link = self.get_next_link()

        return Response(
            OrderedDict(
                [
                    ("next", next_link),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )
