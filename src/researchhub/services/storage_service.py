import logging
import unicodedata
import uuid
from typing import NamedTuple, Optional
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from utils import aws as aws_utils

logger = logging.getLogger(__name__)


class PresignedUrl(NamedTuple):
    object_key: str
    object_url: str
    url: str


SUPPORTED_CONTENT_TYPES = ["application/pdf", "image/png", "image/jpeg"]
SUPPORTED_ENTITIES = ["comment", "note", "paper", "post"]

QUARANTINE_PREFIX = "quarantine/"
"""Prefix within the storage bucket where quarantined objects are moved."""


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
                    "file-name": self._sanitize_filename(filename),
                },
            },
            ExpiresIn=60 * valid_for_min,
        )

        return PresignedUrl(
            url=url,
            object_key=s3_filename,
            object_url=f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{s3_filename}",
        )

    def quarantine_object(self, key: str) -> Optional[str]:
        """
        Move an object to the quarantine prefix within the storage bucket so it
        is no longer served at its original key.

        Returns:
            The new quarantine key on success, or None if the object could not be moved.
        """
        if not key or key.startswith(QUARANTINE_PREFIX):
            return None
        return self._move_object(key, f"{QUARANTINE_PREFIX}{key}")

    def restore_object(self, key: str) -> Optional[str]:
        """
        Move a previously quarantined object back to its original key.
        `key` is the original (non-prefixed) key.

        Returns:
            The restored key on success, or None if the object could not be restored.
        """
        if not key or key.startswith(QUARANTINE_PREFIX):
            return None
        return self._move_object(f"{QUARANTINE_PREFIX}{key}", key)

    def _move_object(self, source_key: str, dest_key: str) -> Optional[str]:
        """
        Move an object within the storage bucket.

        Returns:
            The destination key on success, or None on failure.
        """
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        s3_client = aws_utils.create_client("s3")
        try:
            s3_client.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": source_key},
                Key=dest_key,
            )
            s3_client.delete_object(Bucket=bucket, Key=source_key)
        except (BotoCoreError, ClientError) as e:
            logger.error(
                "Failed to move S3 object from %s to %s: %s", source_key, dest_key, e
            )
            return None
        return dest_key

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for the S3 metadata `file-name` field.

        See: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        """
        name = unicodedata.normalize("NFKD", filename)
        name = name.encode("ascii", "ignore").decode("ascii")
        name = quote(name, safe="!-_.*'()")
        return name
