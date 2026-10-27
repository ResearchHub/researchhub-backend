import logging
import unicodedata
import uuid
from typing import NamedTuple
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.utils.encoding import filepath_to_uri

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

CDN_INVALIDATION_BATCH_SIZE = 1000
"""Maximum number of paths sent in a single CloudFront invalidation request."""


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

    def quarantine_object(self, key: str) -> str | None:
        """
        Move an object to the quarantine prefix within the storage bucket so it
        is no longer served at its original key.

        Returns:
            The new quarantine key on success, or None if the object could not be moved.
        """
        if not key or key.startswith(QUARANTINE_PREFIX):
            return None
        return self._move_object(key, f"{QUARANTINE_PREFIX}{key}")

    def restore_object(self, key: str) -> str | None:
        """
        Move a previously quarantined object back to its original key.
        `key` is the original (non-prefixed) key.

        Returns:
            The restored key on success, or None if the object could not be restored.
        """
        if not key or key.startswith(QUARANTINE_PREFIX):
            return None
        return self._move_object(f"{QUARANTINE_PREFIX}{key}", key)

    def invalidate_cdn_cache(self, keys: list[str]) -> None:
        """
        Evict objects from the storage CDN's edge caches, so that moved objects
        are no longer served at their original key from cache.

        Failures are logged and not raised.
        """
        if not keys:
            return

        distribution_id = settings.AWS_STORAGE_CDN_DISTRIBUTION_ID
        if not distribution_id:
            logger.warning(
                "No storage CDN distribution configured, skipping invalidation "
                "of %d paths",
                len(keys),
            )
            return

        # Match the URL-encoding used when serving objects through the CDN
        paths = sorted({f"/{filepath_to_uri(key)}" for key in keys})
        cloudfront_client = aws_utils.create_client("cloudfront")

        for i in range(0, len(paths), CDN_INVALIDATION_BATCH_SIZE):
            batch = paths[i : i + CDN_INVALIDATION_BATCH_SIZE]
            try:
                cloudfront_client.create_invalidation(
                    DistributionId=distribution_id,
                    InvalidationBatch={
                        "Paths": {"Quantity": len(batch), "Items": batch},
                        "CallerReference": str(uuid.uuid4()),
                    },
                )
            except (BotoCoreError, ClientError) as e:
                logger.error(
                    "Failed to invalidate %d CDN paths in distribution %s: %s",
                    len(batch),
                    distribution_id,
                    e,
                )

    def _move_object(self, source_key: str, dest_key: str) -> str | None:
        """
        Move an object within the storage bucket.

        Returns:
            The destination key on success, or None on failure (including when
            the source object does not exist).
        """
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        s3_client = aws_utils.create_client("s3")

        if not self._object_exists(s3_client, bucket, source_key):
            logger.info("Source object %s does not exist", source_key)
            return None

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

    def _object_exists(self, s3_client, bucket: str, key: str) -> bool:
        """
        Check whether an object exists in the storage bucket.
        """
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            raise

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for the S3 metadata `file-name` field.

        See: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        """
        name = unicodedata.normalize("NFKD", filename)
        name = name.encode("ascii", "ignore").decode("ascii")
        name = quote(name, safe="!-_.*'()")
        return name
