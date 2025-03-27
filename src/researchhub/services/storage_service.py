import uuid
from typing import NamedTuple

from django.conf import settings

from utils import aws as aws_utils


class PresignedUrl(NamedTuple):
    object_key: str
    object_url: str
    url: str


SUPPORTED_CONTENT_TYPES = ["application/pdf", "image/png", "image/jpeg"]
SUPPORTED_ENTITIES = ["comment", "note", "paper", "post"]


class StorageService:
    def create_presigned_url(
        self,
        entity: str,
        filename: str,
        user_id: str,
        content_type: str,
    ) -> PresignedUrl: ...


class S3StorageService(StorageService):
    """
    Service for interacting with S3 storage.
    """

    def create_presigned_url(
        self,
        entity: str,
        filename: str,
        user_id: str,
        content_type: str,
        valid_for_min: int = 2,
    ) -> PresignedUrl:
        """
        Create a presigned URL for uploading a file to S3 that is time-limited.
        """

        if entity not in SUPPORTED_ENTITIES:
            raise ValueError(f"Unsupported entity: {entity}")

        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(f"Unsupported content type: {content_type}")

        s3_filename = f"uploads/{entity}s/users/{user_id}/{uuid.uuid4()}/{filename}"

        s3_client = aws_utils.create_client("s3")

        url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": s3_filename,
                "ContentType": content_type,
                "Metadata": {
                    "created-by-id": f"{user_id}",
                    "file-name": filename,
                },
            },
            ExpiresIn=60 * valid_for_min,
        )

        return PresignedUrl(
            url=url,
            object_key=s3_filename,
            object_url=f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{s3_filename}",
        )
