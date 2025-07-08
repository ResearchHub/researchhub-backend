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

        # Process the content field if it exists
        if "content" in data and data["content"]:
            data["content"] = self._deserialize_json_fields(data["content"])

        return data

    def _deserialize_json_fields(self, data, json_field_names=None):
        """
        Recursively convert JSON strings back to objects in nested structures.
        """
        if json_field_names is None:
            json_field_names = ["comment_content_json"]

        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key in json_field_names and isinstance(value, str):
                    # Convert from JSON string back to object
                    try:
                        result[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        result[key] = value  # leave as-is if parsing fails
                elif isinstance(value, (dict, list)):
                    # Recursively process nested structures
                    result[key] = self._deserialize_json_fields(value, json_field_names)
                else:
                    result[key] = value
            return result
        elif isinstance(data, list):
            return [
                self._deserialize_json_fields(item, json_field_names) for item in data
            ]
        else:
            return data
