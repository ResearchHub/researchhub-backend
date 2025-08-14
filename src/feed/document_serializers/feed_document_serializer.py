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
        Get the content field and process JSON strings back to objects.
        """
        content = getattr(obj, "content", None)
        if not content:
            return content

        # Convert AttrDict to regular dict first
        if hasattr(content, "to_dict"):
            content_dict = content.to_dict()
        elif hasattr(content, "__dict__"):
            content_dict = dict(content)
        else:
            content_dict = content

        # Now process JSON fields
        if content_dict and isinstance(content_dict, dict):
            return self._deserialize_json_fields(content_dict)

        return content_dict

    def get_content_type(self, obj):
        return obj.content_type.model.upper()

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
