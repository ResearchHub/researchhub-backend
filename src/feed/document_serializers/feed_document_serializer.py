import json

from rest_framework import serializers

from search.base.serializers import ElasticsearchSerializer
from search.documents.feed import FeedEntryDocument


class FeedEntryDocumentSerializer(ElasticsearchSerializer):
    content_object = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()

    class Meta:
        document = FeedEntryDocument
        fields = (
            "id",
            "content_type",
            "object_id",
            "content_object",
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

    def get_content_object(self, obj):
        """
        Get the content field and deserialize it from JSON string.
        """
        content = getattr(obj, "content", None)
        if not content:
            return None

        if isinstance(content, dict):
            return content

        if isinstance(content, str):
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return None

        return content

    def get_content_type(self, obj):
        return obj.content_type.model.upper()
