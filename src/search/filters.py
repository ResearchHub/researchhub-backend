from elasticsearch_dsl.query import MultiMatch, Match, MatchPhrase, Fuzzy, MatchAll
from elasticsearch_dsl import Q
from rest_framework import filters

from .utils import practical_score, get_avgdl
from paper.models import Paper


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


class ElasticsearchPaperTitleFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search')
        fields = (
            'title',
            'paper_title'
        )
        search_terms = self.get_search_terms(request)
        terms_count = len(search_terms)
        terms = ' '.join(search_terms)
        threshold = len(terms) # max(score) - len(terms)? # This assumes that the first one is an exact match
        # es.query(explain=True).extra(explain=True).execute().to_dict()
        # x = [len(paper.paper_title.split(' ')) for paper in response]
        query = Match(
            title=terms
        )
        # query = Fuzzy(
        #     paper_title={
        #         'value': terms,
        #         # 'type': 'phrase',
        #         'fuzziness': 'AUTO',
        #     },
        #     title={
        #         'value': terms
        #     }
        # )
        # MultiMatch(
        #     query=terms,
        #     fields=fields,
        #     fuzziness='AUTO',
        # )
        # query = Q(
        #     'multi_match',
        #     query=terms,
        #     fields=fields,
        #     fuzziness='AUTO',
        #     prefix_length=2,
        #     type='phrase'
        # )
        es = search.query(query)
        N = Paper.objects.count()
        dl = len(search_terms)
        avgdl = get_avgdl(es, Paper.objects.all())
        threshold = practical_score(search_terms, N, dl, avgdl) - terms_count
        print(f'threshold: {threshold}')
        response = es.execute()
        for res in response:
            print(res.meta.score)
        response = [res for res in response if res.meta.score >= threshold]
        # import pdb; pdb.set_trace()
        return response
