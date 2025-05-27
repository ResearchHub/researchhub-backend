from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from feed.documents.feed_document import FeedEntryDocument


class FeedEntryDocumentSerializer(DocumentSerializer):
    class Meta:
        document = FeedEntryDocument
        fields = (
            "id",
            "content_type",
            "object_id",
            "content",
            "hot_score",
            "metrics",
            "action",
            "action_date",
            "created_date",
            "updated_date",
            "hubs",
            "unified_document",
            "user",
        )
