from crossref.restful import Works, Prefixes
from crossref_commons.iteration import iterate_publications_as_json
from elasticsearch_dsl import Search
from habanero import Crossref
from rest_framework.decorators import api_view, permission_classes as perms
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from paper.serializers import PaperSerializer
from researchhub.settings import PAGINATION_PAGE_SIZE
from search.filters import ElasticsearchFuzzyFilter
from search.serializers.combined import CombinedSerializer
from search.utils import get_crossref_doi
from search.lib import create_paper_from_crossref
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
        queryset = self.search.query()
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)

        result_space_available = PAGINATION_PAGE_SIZE - response.data['count']

        if result_space_available > 0:
            query = request.query_params.get('search')
            crossref_search_result = search_crossref(query)
            es_dois = self._get_es_dois(response)
            serialized_crossref_papers = self._create_crossref_papers_for_response(  # noqa: E501
                es_dois,
                crossref_search_result,
                result_space_available
            )
            response.data['results'].append(serialized_crossref_papers)

        return response

    def _get_es_dois(self, response):
        es_papers = filter(
            lambda x: (x['meta']['index'] == 'paper'),
            response.data['results']
        )
        es_dois = [paper['doi'] for paper in es_papers]
        return es_dois

    def _create_crossref_papers_for_response(
        self,
        es_dois,
        crossref_result,
        spaces_to_fill
    ):
        crossref_items = crossref_result['message']['items']

        unique_crossref_items = self._strain_duplicates(
            es_dois,
            crossref_items
        )[:spaces_to_fill]

        # TODO: Queue this
        crossref_papers = [
            create_paper_from_crossref(item) for item in unique_crossref_items
        ]

        print(crossref_papers)

        return PaperSerializer(crossref_papers, many=True).data

    def _strain_duplicates(self, es_dois, crossref_items):
        results = []
        for item in crossref_items:
            doi = get_crossref_doi(item)
            if doi not in es_dois:
                results.append(item)
        return results


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
    # res = works.query(bibliographic=term).filter(type='journal-article').facet('orcid', 5)

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
