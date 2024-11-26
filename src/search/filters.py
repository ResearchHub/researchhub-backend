from elasticsearch_dsl import Q, query
from rest_framework import filters


class ElasticsearchFuzzyFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view, search=None, limit=None):
        """
        Builds and executes the elastic search query, returning the response.
        """
        if search is None:
            search = getattr(view, "search")
        fields = getattr(view, "search_fields")
        terms = " ".join(self.get_search_terms(request))

        search_query = Q(
            "function_score",
            query={
                "multi_match": {
                    "query": terms,
                    "fields": fields,
                    "fuzziness": "AUTO",
                }
            },
            functions=[
                query.SF(
                    "script_score",
                    script={
                        "lang": "painless",
                        "inline": "if (!doc.containsKey('score')) { return _score; } else { return (Math.max(0, doc['score'].value) * 10) + _score; }",
                    },
                )
            ],
        )

        es = search.query(search_query)
        if limit:
            es = es[:limit]

        response = es.execute()
        return response
