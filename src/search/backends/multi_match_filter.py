"""
Overriding django-elasticsearch-dsl-drf multi match filter backend
in order to support RH's use case. Changes highlighted below.
"""

from search.backends.multi_match_query import MultiMatchQueryBackend
from search.base.filters import BaseSearchFilterBackend
from search.base.utils import MATCHING_OPTION_SHOULD


class MultiMatchSearchFilterBackend(BaseSearchFilterBackend):
    """Multi match search filter backend."""

    search_param = "search_multi_match"

    """
    Override default matching option "MUST" with "SHOULD" in order
    to support multiple concurrent queries of "best_fields" and "phrase_prefix"
    """
    matching = MATCHING_OPTION_SHOULD

    query_backends = [
        MultiMatchQueryBackend,
    ]

    def filter_queryset(self, request, queryset, view):
        """
        Filter queryset using multi-match query.
        """
        search_query = request.query_params.get(self.search_param, "").strip()
        if not search_query:
            return queryset

        # Get search fields from view
        search_fields = getattr(view, "search_fields", {})
        if not search_fields:
            return queryset

        # Use the multi-match query backend
        for backend_class in self.query_backends:
            backend = backend_class()
            queryset = backend.filter(queryset, search_query, search_fields)

        return queryset

    """
    Override parent mixin because it splits queries on ":" character
    See: https://github.com/barseghyanartur/django-elasticsearch-dsl-drf/issues/84
    """

    @classmethod
    def split_lookup_name(cls, value, maxsplit=-1):
        return [value]
