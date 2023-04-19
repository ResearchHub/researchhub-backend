from django_elasticsearch_dsl_drf.constants import SUGGESTER_COMPLETION
from django_elasticsearch_dsl_drf.filter_backends import SuggesterFilterBackend
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.user import UserDocument
from search.serializers.user import UserDocumentSerializer
from utils.permissions import ReadOnly


class UserDocumentView(DocumentViewSet):
    document = UserDocument
    permission_classes = [ReadOnly]
    serializer_class = UserDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        SuggesterFilterBackend,
    ]
    suggester_fields = {
        "full_name_suggest": {
            "field": "full_name_suggest",
            "suggesters": ["completion"],
            "options": {
                "size": 10,
            },
        },
    }

    # search_fields = {
    #     'full_name': {'boost': 2, 'fuzziness': 1},
    #     'description': {'boost': 1, 'fuzziness': 1},
    #     'headline.title': {'boost': 1, 'fuzziness': 1},
    # }

    # multi_match_search_fields = {
    #     'full_name': {'boost': 2},
    #     'description': {'boost': 1},
    #     'headline.title': {'boost': 1},
    # }

    # multi_match_options = {
    #     'operator': 'and',
    #     'type': 'cross_fields',
    #     'analyzer': 'content_analyzer',
    # }

    # faceted_search_fields = {
    #     'person_types': 'person_types'
    # }

    # post_filter_fields = {
    #     'person_types': 'person_types'
    # }

    # ordering_fields = {
    #     'author_score': 'author_score',
    #     'user_reputation': 'user_reputation',
    # }

    # def __init__(self, *args, **kwargs):
    #     self.search = Search(index=['person'])
    #     super(PersonDocumentView, self).__init__(*args, **kwargs)

    # def _filter_queryset(self, request):
    #     queryset = self.search

    #     for backend in list(self.filter_backends):
    #         queryset = backend().filter_queryset(
    #         request,
    #         queryset,
    #         self,
    #     )

    #     return queryset
