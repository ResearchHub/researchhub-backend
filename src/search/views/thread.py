from rest_framework import viewsets
from elasticsearch_dsl import Search
from elasticsearch_dsl.connections import connections

from search.documents.thread import ThreadDocument
from search.filters import ElasticsearchFuzzyFilter
from search.serializers.thread import ThreadDocumentSerializer
from utils.permissions import ReadOnly


class ThreadDocumentView(viewsets.ReadOnlyModelViewSet):
    document = ThreadDocument
    serializer_class = ThreadDocumentSerializer
    permission_classes = [ReadOnly]
    filter_backends = [ElasticsearchFuzzyFilter]

    search_fields = ['title']

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
        super(ThreadDocumentView, self).__init__(*args, **kwargs)

    def get_queryset(self):
        queryset = self.search.query()
        queryset.model = self.document.Django.model
        return queryset
