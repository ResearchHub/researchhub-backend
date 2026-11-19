from collections.abc import Iterable

from rest_framework import serializers

from researchhub.services.storage_service import (
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_ENTITIES,
    UPLOAD_METHOD_PUT,
    UPLOAD_METHODS,
    S3StorageService,
    UploadVerificationError,
)


class AssetUploadRequestSerializer(serializers.Serializer):
    """
    Serializer for uploading an asset into ResearchHub storage.
    Used to validate request data.
    """

    content_type = serializers.ChoiceField(choices=SUPPORTED_CONTENT_TYPES)
    entity = serializers.ChoiceField(choices=SUPPORTED_ENTITIES)
    filename = serializers.CharField(required=True)
    upload_method = serializers.ChoiceField(
        choices=UPLOAD_METHODS, default=UPLOAD_METHOD_PUT
    )


def validate_uploaded_assets(
    references: Iterable[str | None],
    attached: Iterable[str | None] = (),
) -> None:
    try:
        S3StorageService().verify_uploads(references, attached)
    except UploadVerificationError as e:
        raise serializers.ValidationError({"image": [str(e)]}) from e
