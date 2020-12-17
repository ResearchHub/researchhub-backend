from elasticsearch_dsl.query import Match
from elasticsearch_dsl import query, Q
from rest_framework import filters

from .utils import practical_score, get_avgdl
from paper.models import Paper


class ElasticsearchFuzzyFilter(filters.SearchFilter):

    def filter_queryset(
        self,
        request,
        queryset,
        view,
        search=None,
        limit=None
    ):
        """
        Builds and executes the elastic search query, returning the response.
        """
        if search is None:
            search = getattr(view, 'search')
        fields = getattr(view, 'search_fields')
        terms = ' '.join(self.get_search_terms(request))

        search_query = Q(
            'function_score',
            query={
                'multi_match': {
                    'query': terms,
                    'fields': fields,
                    'fuzziness': 'AUTO',
                }
            },
            functions=[
                query.SF(
                    'script_score',
                    script={
                        'lang': 'painless',
                        'inline': "if (!doc.containsKey('score')) { return _score; } else { return (Math.max(0, doc['score'].value) * 10) + _score; }"
                    }
                )
            ]
        )

        es = search.query(search_query)
        if limit:
            es = es[:limit]

        response = es.execute()
        return response


class ElasticsearchPaperTitleFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search')

        search_terms = self.get_search_terms(request)
        terms_count = len(search_terms)
        terms = ' '.join(search_terms)
        query = Match(
            title=terms
        )

        es = search.query(query)
        N = Paper.objects.count()
        dl = len(search_terms)
        avgdl = get_avgdl(es, Paper.objects)
        threshold = practical_score(search_terms, N, dl, avgdl) - terms_count
        response = es.execute()
        response = [res for res in response if res.meta.score >= threshold]
        return response
