from rest_framework.generics import ListAPIView
from elasticsearch_dsl import Search

from search.filters import ElasticsearchFuzzyFilter
from search.serializers.combined import CombinedSerializer
from utils.permissions import ReadOnly


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
