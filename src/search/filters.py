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


class ElasticsearchFuzzyFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search')
        fields = getattr(view, 'search_fields')
        terms = ' '.join(self.get_search_terms(request))

        query = Fuzzy(** {fields[0]: terms})

        iterfields = iter(fields)
        next(iterfields)
        for field in iterfields:
            query = query | Fuzzy(** {field: terms})

        es = search.query(query)

        response = es.execute()
        return response
