"""
Overriding django-elasticsearch-dsl-drf multi match filter backend 
in order to support RH's use case. Changes highlighted below.
"""
from django_elasticsearch_dsl_drf.filter_backends.search import BaseSearchFilterBackend
from django_elasticsearch_dsl_drf.constants import MATCHING_OPTION_SHOULD

from search.backends.multi_match_query import MultiMatchQueryBackend

class MultiMatchSearchFilterBackend(BaseSearchFilterBackend):
    """Multi match search filter backend."""

    search_param = 'search_multi_match'

    """
    Override default matching option "MUST" with "SHOULD" in order
    to support multiple concurrent queries of "best_fields" and "phrase_prefix"
    """
    matching = MATCHING_OPTION_SHOULD

    query_backends = [
        MultiMatchQueryBackend,
    ]

    """
    Override parent mixin because it splits queries on ":" character
    See: https://github.com/barseghyanartur/django-elasticsearch-dsl-drf/issues/84
    """
    @classmethod
    def split_lookup_name(cls, value, maxsplit=-1):
        return [value]
