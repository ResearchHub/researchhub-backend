from rest_framework import serializers

from feed.serializers import RelatedWorkSerializer


class ExcludedFromFeedWorkSerializer(RelatedWorkSerializer):
    """RelatedWork payload with ids remapped for hide/unhide restore."""

    document_id = serializers.SerializerMethodField()

    def get_id(self, unified_document):
        return unified_document.id

    def get_document_id(self, unified_document):
        content = self._get_content(unified_document)
        return content.id if content else None

    def to_representation(self, unified_document):
        data = super().to_representation(unified_document)
        if data is None:
            return None
        data.pop("unified_document_id", None)
        return data
