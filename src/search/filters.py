from rest_framework import filters
from elasticsearch_dsl.query import Fuzzy
from elasticsearch_dsl import Q


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


class ElasticsearchFuzzyFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search')
        fields = getattr(view, 'search_fields')
        terms = ' '.join(self.get_search_terms(request))
        query = Q("multi_match", query=terms, fields=fields, fuzziness="AUTO")
        es = search.query(query)

        response = es.execute()
        return response
