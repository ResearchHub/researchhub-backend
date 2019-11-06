from rest_framework import serializers
from rest_framework.generics import ListAPIView
from elasticsearch_dsl import Search

from search.filters import ElasticsearchFuzzyFilter
from search.serializers.combo import ComboSerializer
from utils.permissions import ReadOnly


class ComboView(ListAPIView):
    indices = ['papers', 'authors', 'discussion_threads', 'hubs']
    serializer_class = ComboSerializer

    permission_classes = [ReadOnly]
    filter_backends = [ElasticsearchFuzzyFilter]

    search_fields = ['title', 'first_name', 'last_name', 'authors', 'name']

    def __init__(self, *args, **kwargs):
        assert self.indices is not None

        self.search = Search(index=self.indices).highlight(
            *self.search_fields,
            fragment_size=50
        )

        super(ComboView, self).__init__(*args, **kwargs)

    def get_queryset(self):
        queryset = self.search.query()
        return queryset
