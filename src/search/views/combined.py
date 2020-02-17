from elasticsearch_dsl import Search
from elasticsearch_dsl.utils import AttrDict
from habanero import Crossref
from rest_framework.decorators import api_view, permission_classes as perms
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from researchhub.settings import PAGINATION_PAGE_SIZE
from search.filters import ElasticsearchFuzzyFilter
# from search.lib import create_paper_from_crossref
from search.serializers.combined import CombinedSerializer
# from search.tasks import queue_create_crossref_papers
from search.utils import get_crossref_doi
from utils.permissions import ReadOnly
from utils.http import RequestMethods


class CombinedView(ListAPIView):
    indices = [
        'paper',
        'author',
        'discussion_thread',
        'hub',
        'summary',
        'university'
    ]
    serializer_class = CombinedSerializer

    permission_classes = [ReadOnly]
    filter_backends = [ElasticsearchFuzzyFilter]

    search_fields = [
        'doi',
        'title',
        'tagline',
        'first_name',
        'last_name',
        'authors',
        'name',
        'summary_plain_text',
        'plain_text',
    ]

    def __init__(self, *args, **kwargs):
        assert self.indices is not None

        self.search = Search(index=self.indices).highlight(
            *self.search_fields,
            fragment_size=50
        )

        super(CombinedView, self).__init__(*args, **kwargs)

    def get_queryset(self):
        es_search = self.search.query()
        return es_search

    def list(self, request, *args, **kwargs):
        es_response_queryset = self.filter_queryset(self.get_queryset())
        es_response_queryset = self._add_crossref_results(
            request,
            es_response_queryset
        )

        page = self.paginate_queryset(es_response_queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(es_response_queryset, many=True)
        return Response(serializer.data)

    def _add_crossref_results(self, request, es_response):
        result_space_available = PAGINATION_PAGE_SIZE - len(es_response.hits)

        if result_space_available > 0:
            query = request.query_params.get('search')
            crossref_search_result = search_crossref(query)
            es_dois = self._get_es_dois(es_response.hits)
            crossref_hits = self._create_crossref_hits(
                es_dois,
                crossref_search_result,
                result_space_available
            )
            es_response.hits.extend(crossref_hits)

        return es_response

    def _get_es_dois(self, hits):
        es_papers = filter(lambda hit: (hit.meta['index'] == 'paper'), hits)
        es_dois = [paper['doi'] for paper in es_papers]
        return es_dois

    def _create_crossref_hits(
        self,
        existing_dois,
        crossref_result,
        amount
    ):
        items = crossref_result['message']['items']
        items = self._remove_duplicate_papers(existing_dois, items)[:amount]
        hits = self._build_crossref_hits(items)

        # TODO: Queue creating the paper
        # queue_create_crossref_papers(unique_crossref_items)

        return hits

    def _remove_duplicate_papers(self, es_dois, crossref_items):
        results = []
        for item in crossref_items:
            doi = get_crossref_doi(item)
            if doi not in es_dois:
                results.append(item)
        return results

    def _build_crossref_hits(self, items):
        hits = []
        for item in items:
            meta = self._build_crossref_meta(item)
            hit = AttrDict({
                'meta': AttrDict(meta),
                'title': item['title'][0],
                'paper_title': item['title'],
                'doi': item['DOI'],
                'url': item['URL'],
            })
            hits.append(hit)
        return hits

    def _build_crossref_meta(self, item):
        # TODO: Add highlight
        return {
            'index': 'crossref_paper',
            'id': None,
            'score': -1,
            'highlight': None,
        }


@api_view([RequestMethods.GET])
@perms([ReadOnly])
def crossref(request):
    query = request.query_params.get('query')
    results = search_crossref(query)
    return Response(results)


def search_crossref(query):
    results = []
    cr = Crossref()
    filters = {'type': 'journal-article'}
    results = cr.works(
        query_bibliographic=query,
        limit=10,
        filter=filters
    )

    # TODO: Compare response times

    # crossrefapi
    #
    # works = Works()
    # res = works.query(bibliographic=term).filter(type='journal-article')
    # .facet('orcid', 5)

    # commons
    #
    # filters = {'type': 'journal-article'}
    # queries = {'query.bibliographic': term}
    # results = iterate_publications_as_json(
    #     max_results=5,
    #     filter=filters,
    #     queries=queries
    # )

    return results
