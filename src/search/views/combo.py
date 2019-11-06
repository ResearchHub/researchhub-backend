from rest_framework.generics import ListAPIView
from elasticsearch_dsl import Search
from elasticsearch_dsl.connections import connections

from search.documents import AuthorDocument
from search.serializers import AuthorDocumentSerializer
from utils.permissions import ReadOnly


class ElasticsearchFilter(filters.SearchFilter):

    def filter_queryset(self, request, queryset, view):
        search = getattr(view, 'search', None)
        fields = getattr(view, 'search_fields')
        terms = ' '.join(self.get_search_terms(request))

        q = Fuzzy(** {fields[0]: terms})

        iterfields = iter(fields)
        next(iterfields)
        for field in iterfields:
            q = q | Fuzzy(** {field: terms})

        # q = Q('fuzzy', query=terms, fields=fields)
        s = search.query(q)

        response = s.execute()
        return response


class ComboView(ListAPIView):
    indices = ['papers', 'authors', 'discussion_threads', 'hubs']
    # serializer_class = ComboSerializer

    permission_classes = [ReadOnly]
    filter_backends = [ElasticsearchFilter]

    search_fields = ['title', 'first_name', 'last_name', 'authors', 'name']

    def __init__(self, *args, **kwargs):
        assert self.indices is not None

        self.search = Search(index=self.indices)

        super(ComboView, self).__init__(*args, **kwargs)

    def get_queryset(self):
        queryset = self.search.query()
        return queryset
