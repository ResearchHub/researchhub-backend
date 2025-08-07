from collections import OrderedDict

from rest_framework.pagination import LimitOffsetPagination as DRFLimitOffsetPagination
from rest_framework.response import Response


class LimitOffsetPagination(DRFLimitOffsetPagination):
    """
    Limit/offset pagination for Elasticsearch results.
    Extends DRF's LimitOffsetPagination to work with Elasticsearch.
    """

    default_limit = 10
    limit_query_param = "limit"
    offset_query_param = "offset"
    max_limit = 100

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate Elasticsearch queryset.
        """
        self.request = request  # Store request for get_next_link/get_previous_link
        self.limit = self.get_limit(request)
        if self.limit is None:
            return None

        self.offset = self.get_offset(request)

        # Apply limit and offset to Elasticsearch query
        queryset = queryset[self.offset : self.offset + self.limit]

        # Execute the query and store response
        self.response = queryset.execute()

        # Store the count
        self.count = self.response.hits.total.value

        # Return the hits
        return self.response.hits

    def get_paginated_response(self, data):
        """
        Return paginated response with Elasticsearch metadata.
        """
        return Response(
            OrderedDict(
                [
                    ("count", self.count),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )

    def get_paginated_response_schema(self, schema):
        """
        Return OpenAPI schema for paginated response.
        """
        return {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "example": 123,
                },
                "next": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "http://api.example.org/accounts/?offset=400&limit=100",
                },
                "previous": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "http://api.example.org/accounts/?offset=200&limit=100",
                },
                "results": schema,
            },
        }
