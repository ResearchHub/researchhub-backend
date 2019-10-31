from rest_framework import filters


class ElasticsearchFilter(filters.SearchFilter):
    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search', None)
        s = search.query(
            'multi_match',
            query=' '.join(self.get_search_terms(request)),
            fields=self.get_search_fields(view, request)
        )
        response = s.execute()
        return response
