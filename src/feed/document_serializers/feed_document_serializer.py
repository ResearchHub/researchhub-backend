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

    def to_representation(self, instance):
        """
        Override to properly serialize SerializerMethodFields.
        The base ElasticsearchSerializer.to_representation() just converts
        the document to a dict, bypassing SerializerMethodField processing.
        """
        # Get base document data
        data = super().to_representation(instance)

        # Build the final representation using declared fields
        representation = {}
        for field_name in self.Meta.fields:
            # Get the field from the serializer
            field = self.fields.get(field_name)

            if field:
                # Use the field's to_representation method
                # For SerializerMethodField, this calls the get_* method
                value = field.to_representation(field.get_attribute(instance))
                representation[field_name] = value
            elif field_name in data:
                # Field not declared, use raw data from document
                representation[field_name] = data[field_name]

        return representation

    def get_author(self, obj):
        """
        Return author data from OpenSearch document.
        In OpenSearch, author is already prepared as a dict.
        """
        author = getattr(obj, "author", None)
        if author:
            # OpenSearch returns AttrDict/dict, convert to plain dict
            if hasattr(author, "to_dict"):
                return author.to_dict()
            elif isinstance(author, dict):
                return author
        return None

    def get_hot_score_v2(self, obj):
        """Return hot_score as hot_score_v2 to match original endpoint"""
        return getattr(obj, "hot_score", 0)

    def get_hot_score_breakdown(self, obj):
        """
        Return hot score breakdown if explicitly requested via query param.

        NOTE: hot_score_v2_breakdown is NOT stored in OpenSearch, only in the database.
        For v2 endpoint, this will always return None until the field is added to
        the OpenSearch document.
        """
        request = self.context.get("request")
        if not request:
            return None

        # Only include if explicitly requested
        include = request.query_params.get("include_hot_score_breakdown", "false")
        if include.lower() != "true":
            return None

        # This field doesn't exist in OpenSearch document
        # Would need to add to FeedEntryDocument and re-index
        hot_score_breakdown = getattr(obj, "hot_score_v2_breakdown", None)
        return hot_score_breakdown if hot_score_breakdown else None

    def get_external_metadata(self, obj):
        """
        Return external_metadata from Paper if content is a Paper.
        Returns None for non-paper content.

        NOTE: external_metadata is NOT stored in the OpenSearch content JSON.
        The PaperSerializer doesn't include it when serializing content.
        For v2 endpoint, this will return None unless external_metadata is added to
        the OpenSearch document or included in the content serialization.
        """
        content_type = getattr(obj, "content_type", None)
        if content_type and content_type.model == "paper":
            content = self.get_content_object(obj)
            if content and isinstance(content, dict):
                # Try to get it from content, but it's likely not there
                return content.get("external_metadata")
        return None

    def get_content_object(self, obj):
        """
        Get the content field and deserialize it from JSON string.

        In OpenSearch, content is stored as a TextField (JSON string) via
        FeedEntryDocument.prepare_content() which calls json.dumps().
        This method deserializes it back to a dict.
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
