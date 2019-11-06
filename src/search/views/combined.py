from elasticsearch_dsl import Search
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from search.serializers import (
    AuthorDocumentSerializer,
    HubDocumentSerializer,
    PaperDocumentSerializer,
    ThreadDocumentSerializer,
)


class CombinedView(ListAPIView):

    pagination_class = PageNumberPagination
    permission_classes = (AllowAny,)
    ignore = []

    def __init__(self, *args, **kwargs):
        assert self.document is not None

        self.client = connections.get_connection(
            self.document._get_using()
        )
        self.index = self.document._index._name
        self.mapping = self.document._doc_type.mapping.properties.name
        self.search = Search(
            using=self.client,
            index=self.index,
            doc_type=self.document._doc_type.name
        )
        super(BaseDocumentViewSet, self).__init__(*args, **kwargs)

    def get_queryset(self):
        """Get queryset."""
        queryset = self.search.query()
        # Model- and object-permissions of the Django REST framework (
        # at the moment of writing they are ``DjangoModelPermissions``,
        # ``DjangoModelPermissionsOrAnonReadOnly`` and
        # ``DjangoObjectPermissions``) require ``model`` attribute to be
        # present in the queryset. Unfortunately we don't have that here.
        # The following approach seems to fix that (pretty well), since
        # model and object permissions would work out of the box (for the
        # correspondent Django model/object). Alternative ways to solve this
        # issue are: (a) set the ``_ignore_model_permissions`` to True on the
        # ``BaseDocumentViewSet`` or (b) provide alternative permission classes
        # that are almost identical to the above mentioned classes with
        # the only difference that they know how to extract the model from the
        # given queryset. If you think that chosen solution is incorrect,
        # please make an issue or submit a pull request explaining the
        # disadvantages (and ideally - propose  a better solution). Couple of
        # pros for current solution: (1) works out of the box, (2) does not
        # require modifications of current permissions (which would mean we
        # would have to keep up with permission changes of the DRF).
        queryset.model = self.document.Django.model
        return queryset

@api_view(['GET'])
@permission_classes(())
def search(request):
    """
    Pings elasticsearch to do a combined search
    """

    search = request.GET.get('search')
    page = request.GET.get('page', 1)
    size = request.GET.get('size', 10)
    s = Search(
        index=['papers', 'authors', 'discussion_threads', 'hubs']
    ).query(
        'query_string',
        query='{}*'.format(search),
        fields=['title', 'first_name', 'last_name', 'authors', 'name']
    ).highlight(
        'title',
        'first_name',
        'last_name',
        'authors',
        'name',
        fragment_size=50
    )

    result = s.execute()

    # Paginate the ES results
    # They are already paginated?
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
        elif hit.meta.index == 'hubs':
            res = HubDocumentSerializer(hit).data

        if res:
            res['meta'] = hit.meta.to_dict()
            results.append(res)

    response = {
        'count': total_count,
        'results': results,
    }

    return Response(response)
