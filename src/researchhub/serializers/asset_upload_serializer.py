from rest_framework import serializers

from researchhub.services.storage_service import (
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_ENTITIES,
)


class AssetUploadSerializer(serializers.Serializer):
    """
    Serializer for uploading an asset into ResearchHub storage.
    Used to validate request data.
    """

    content_type = serializers.ChoiceField(choices=SUPPORTED_CONTENT_TYPES)
    entity = serializers.ChoiceField(choices=SUPPORTED_ENTITIES)
    filename = serializers.CharField(required=True)
