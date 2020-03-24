from rest_framework import filters
from elasticsearch_dsl import Q


class ElasticsearchFuzzyFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search')
        fields = getattr(view, 'search_fields')
        terms = ' '.join(self.get_search_terms(request))
        query = Q(
            'multi_match',
            query=terms,
            fields=fields,
            fuzziness='AUTO'
        )
        es = search.query(query)

        response = es.execute()
        return response
