from django_elasticsearch_dsl_drf.filter_backends import (
    DefaultOrderingFilterBackend,
    FilteringFilterBackend,
    OrderingFilterBackend,
    SearchFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet

from feed.document_serializers.feed_document_serializer import (
    FeedEntryDocumentSerializer,
)
from feed.documents.feed_document import FeedEntryDocument


class FeedV2ViewSet(DocumentViewSet):
    """
    ViewSet for accessing the main feed of ResearchHub activities using Elasticsearch.
    """

    document = FeedEntryDocument
    permission_classes = []
    serializer_class = FeedEntryDocumentSerializer
    pagination_class = LimitOffsetPagination

    filter_backends = [
        FilteringFilterBackend,
        OrderingFilterBackend,
        DefaultOrderingFilterBackend,
        SearchFilterBackend,
    ]

    filter_fields = {
        "hub": "hubs.slug",
    }

    ordering_fields = {
        "action_date": "action_date",
        "hot_score": "hot_score",
        "created_date": "created_date",
    }

    ordering = ("-action_date",)
