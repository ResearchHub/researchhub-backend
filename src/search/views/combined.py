from elasticsearch_dsl import Search
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from search.serializers.paper import PaperDocumentSerializer
from search.serializers.author import AuthorDocumentSerializer
from search.serializers.thread import ThreadDocumentSerializer

@api_view(['GET'])
@permission_classes(())
def search(request):
    """
    Pings elasticsearch to do a combined search
    """

    search = request.GET.get('search')
    page = request.GET.get('page', 1)
    size = request.GET.get('size', 10)
    s = Search(index=['papers', 'authors', 'discussion_threads']) \
    .query("query_string", query='{}*'.format(search), fields=['title', 'first_name', 'last_name', 'authors']) \
    .highlight('title', 'first_name', 'last_name', 'authors', fragment_size=50)

    result = s.execute()

    # Paginate the ES results
    first = (page - 1) * size
    last = first + size
    total_count = len(result)
    result = result[first:last]

    results = []
    for hit in result:
        res = None
        if hit.meta.index == 'papers':
            res = PaperDocumentSerializer(hit).data
        elif hit.meta.index == 'authors':
            res = AuthorDocumentSerializer(hit).data
        elif hit.meta.index == 'threads':
            res = ThreadDocumentSerializer(hit).data
        
        if res:
            res['meta'] = hit.meta.to_dict()
            results.append(res)

    response = {
        'count': total_count,
        'results': results,
    }

    return Response(response)

