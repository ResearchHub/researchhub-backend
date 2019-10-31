from rest_framework import filters
from elasticsearch_dsl.query import Fuzzy


class ElasticsearchFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search', None)
        terms = ' '.join(self.get_search_terms(request))

        # TODO: Get field names from request instead of hardcoding
        # fuzzy_field = request.get('fuzzy', None)
        f = Fuzzy(** {'first_name': terms})
        s = search.query(f)

        response = s.execute()
        return response
