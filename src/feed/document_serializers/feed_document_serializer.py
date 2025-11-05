import json

from rest_framework import serializers

from feed.serializers import SimpleAuthorSerializer
from search.base.serializers import ElasticsearchSerializer
from search.documents.feed import FeedEntryDocument


class FeedEntryDocumentSerializer(ElasticsearchSerializer):
    content_object = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    hot_score_v2 = serializers.SerializerMethodField()
    hot_score_breakdown = serializers.SerializerMethodField()
    external_metadata = serializers.SerializerMethodField()

    class Meta:
        document = FeedEntryDocument
        fields = (
            "id",
            "content_type",
            "content_object",
            "created_date",
            "action_date",
            "action",
            "author",
            "metrics",
            "hot_score_v2",
            "hot_score_breakdown",
            "external_metadata",
        )

    def get_author(self, obj):
        """Return author data only if feed entry has an associated user"""
        user = getattr(obj, "user", None)
        if user and hasattr(user, "author_profile"):
            return SimpleAuthorSerializer(user.author_profile).data
        return None

    def get_hot_score_v2(self, obj):
        """Return hot_score as hot_score_v2 to match original endpoint"""
        return getattr(obj, "hot_score", 0)

    def get_hot_score_breakdown(self, obj):
        """Return hot score breakdown if explicitly requested via query param."""
        request = self.context.get("request")
        if not request:
            return None

        # Only include if explicitly requested
        include = request.query_params.get("include_hot_score_breakdown", "false")
        if include.lower() != "true":
            return None

        # Return stored breakdown (already calculated)
        hot_score_breakdown = getattr(obj, "hot_score_v2_breakdown", None)
        return hot_score_breakdown if hot_score_breakdown else None

    def get_external_metadata(self, obj):
        """
        Return external_metadata from Paper if content is a Paper.
        Returns None for non-paper content.
        """
        content_type = getattr(obj, "content_type", None)
        if content_type and content_type.model == "paper":
            content = self.get_content_object(obj)
            if content and isinstance(content, dict):
                return content.get("external_metadata")
        return None

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
