from rest_framework import filters
from elasticsearch_dsl.query import MultiMatch, Match, MatchPhrase, Fuzzy, MatchAll
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


class ElasticsearchPaperTitleFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search')
        fields = (
            'title',
            'paper_title'
        )
        terms = ' '.join(self.get_search_terms(request))
        threshold = len(terms) # max(score) - len(terms)?
        # es.query(explain=True).extra(explain=True).execute().to_dict()
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
        response = es.execute()
        # import pdb; pdb.set_trace()
        for res in response:
            print(res.meta.score)
        return response
