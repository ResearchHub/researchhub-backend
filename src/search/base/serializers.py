from opensearchpy import Document
from rest_framework import serializers


class ElasticsearchSerializer(serializers.Serializer):
    """
    Base serializer for Elasticsearch documents.
    Replaces django_elasticsearch_dsl_drf.serializers.DocumentSerializer
    """

    def to_representation(self, instance):
        """
        Convert an Elasticsearch document to a dictionary.
        Handles custom field functions like SerializerMethodField.
        Only includes fields specified in Meta.fields if present.
        """
        if not isinstance(instance, Document):
            raise TypeError("Expected an instance of opensearchpy.Document")

        # Convert Document instance to dictionary
        data = instance.to_dict()

        # Add meta fields if they exist
        if hasattr(instance, "meta"):
            meta = instance.meta
            if hasattr(meta, "id"):
                data["id"] = meta.id
            if hasattr(meta, "score"):
                data["_score"] = meta.score
            if hasattr(meta, "highlight"):
                data["highlight"] = meta.highlight.to_dict()

        # Get the list of allowed fields from Meta.fields if it exists
        allowed_fields = None
        if hasattr(self, "Meta") and hasattr(self.Meta, "fields"):
            allowed_fields = set(self.Meta.fields)
            data = {k: v for k, v in data.items() if k in allowed_fields}

        # Process declared fields to handle SerializerMethodField and other
        # custom fields. These will override the document data.
        fields = self._readable_fields

        for field in fields:
            # Skip if field is not in allowed_fields
            if allowed_fields and field.field_name not in allowed_fields:
                continue

            try:
                attribute = field.get_attribute(instance)
                # Transform the value using the field's to_representation
                if attribute is not None:
                    data[field.field_name] = field.to_representation(attribute)
                else:
                    data[field.field_name] = None
            except (AttributeError, Exception):
                # If we can't get the attribute, skip this field
                continue

        return data

    def to_internal_value(self, data):
        """
        We don't need to handle deserialization for ES documents.
        """
        raise NotImplementedError(
            "Elasticsearch documents are read-only through this serializer"
        )


class ElasticsearchListSerializer(serializers.ListSerializer):
    """
    List serializer for handling multiple Elasticsearch documents.
    """

    def to_representation(self, data):
        """
        Handle both Search responses and lists of documents.
        """
        # If it's a Search response with hits
        if hasattr(data, "hits"):
            return [self.child.to_representation(hit) for hit in data.hits]

        # Otherwise treat as iterable
        return [self.child.to_representation(item) for item in data]
