import json

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

    def to_representation(self, instance):
        """
        Convert JSON strings back to objects for API response.
        """
        data = super().to_representation(instance)

        # Parse JSON strings back to objects in the content field
        if "content" in data and isinstance(data["content"], dict):
            content = data["content"]

            # Parse `comment_content_json` if it's a string
            if "comment_content_json" in content and isinstance(
                content["comment_content_json"], str
            ):
                try:
                    content["comment_content_json"] = json.loads(
                        content["comment_content_json"]
                    )
                except (json.JSONDecodeError, TypeError):
                    pass  # leave as-is

            # Parse parent_comment if it's a string
            if "parent_comment" in content and isinstance(
                content["parent_comment"], str
            ):
                try:
                    content["parent_comment"] = json.loads(content["parent_comment"])
                except (json.JSONDecodeError, TypeError):
                    pass  # leave as-is

        return data
