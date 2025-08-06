from elasticsearch_dsl import Document
from rest_framework import serializers


class ElasticsearchSerializer(serializers.Serializer):
    """
    Base serializer for Elasticsearch documents.
    Replaces django_elasticsearch_dsl_drf.serializers.DocumentSerializer
    """

    def to_representation(self, instance):
        """
        Convert an Elasticsearch document to a dictionary.
        """
        if isinstance(instance, Document):
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

            return data

        # If it's already a dict (from ES response), return as is
        return instance

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


# Alias for compatibility with django_elasticsearch_dsl_drf
DocumentSerializer = ElasticsearchSerializer
