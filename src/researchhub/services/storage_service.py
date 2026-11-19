import logging
import posixpath
import re
import unicodedata
import uuid
from collections.abc import Iterable
from typing import NamedTuple
from urllib.parse import quote, unquote, urlparse

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from researchhub.services.image_upload_service import MAX_IMAGE_UPLOAD_BYTES
from utils import aws as aws_utils

logger = logging.getLogger(__name__)


class PresignedUrl(NamedTuple):
    object_key: str
    object_url: str
    url: str


class PresignedPost(NamedTuple):
    object_key: str
    object_url: str
    url: str
    fields: dict[str, str]
    max_bytes: int


class UploadVerificationError(ValueError):
    pass


SUPPORTED_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ("pdf",),
    "image/png": ("png",),
    "image/jpeg": ("jpg", "jpeg"),
}
SUPPORTED_CONTENT_TYPES = list(SUPPORTED_CONTENT_TYPE_EXTENSIONS)
SUPPORTED_ENTITIES = ["comment", "note", "paper", "post"]

UPLOAD_METHOD_POST = "post"
UPLOAD_METHOD_PUT = "put"
UPLOAD_METHODS = [UPLOAD_METHOD_PUT, UPLOAD_METHOD_POST]

MAX_UPLOAD_BYTES = {
    "application/pdf": 25 * 1024 * 1024,
    "image/png": MAX_IMAGE_UPLOAD_BYTES,
    "image/jpeg": MAX_IMAGE_UPLOAD_BYTES,
}
CONTENT_SIGNATURES = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
}
_SIGNATURE_BYTES = max(len(signature) for signature in CONTENT_SIGNATURES.values())
_UPLOAD_KEY = re.compile(
    rf"uploads/(?:{'|'.join(f'{entity}s' for entity in SUPPORTED_ENTITIES)})"
    r"/users/[^/]+/[^/]+/.+",
    re.DOTALL,
)

QUARANTINE_PREFIX = "quarantine/"
"""Prefix within the storage bucket where quarantined objects are moved."""


def object_key_from_url(url: str | None) -> str | None:
    """
    Return the object key of a URL served from the storage bucket's domain
    (e.g. a `PresignedUrl.object_url`), or None if it points anywhere else.
    """
    if not url:
        return None

    domain = settings.AWS_S3_CUSTOM_DOMAIN
    if not domain:
        return None
    # The configured domain may or may not include a scheme.
    bucket_host = urlparse(domain if "://" in domain else f"//{domain}").netloc

    # Object URLs are built from the raw, unencoded key (see `create_presigned_url`),
    # so the key is everything after the host, including any `;`, `?` or `#`.
    _, sep, rest = url.partition("://")
    host, _, key = rest.partition("/")
    if not sep or host.lower() != bucket_host.lower():
        return None

    return key or None


def uploaded_object_key(reference: object) -> str | None:
    if not reference or not isinstance(reference, str):
        return None

    url_key = object_key_from_url(reference)
    key = reference if url_key is None else unquote(url_key)
    key = posixpath.normpath(key.replace("\\", "/")).lstrip("/")
    return key if _UPLOAD_KEY.fullmatch(key) else None


class StorageService:
    def create_presigned_url(
        self,
        entity: str,
        filename: str,
        user_id: str,
        content_type: str,
    ) -> PresignedUrl: ...

    def create_presigned_post(
        self,
        entity: str,
        filename: str,
        user_id: str,
        content_type: str,
    ) -> PresignedPost: ...


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

        s3_filename = self._new_upload_key(entity, filename, user_id, content_type)

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

    def create_presigned_post(
        self,
        entity: str,
        filename: str,
        user_id: str,
        content_type: str,
        valid_for_min: int = 2,
    ) -> PresignedPost:
        key = self._new_upload_key(entity, filename, user_id, content_type)
        max_bytes = MAX_UPLOAD_BYTES[content_type]
        fields = {
            "Content-Type": content_type,
            "x-amz-meta-created-by-id": f"{user_id}",
            "x-amz-meta-file-name": self._sanitize_filename(filename),
        }

        response = aws_utils.create_client("s3").generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=key,
            Fields=fields,
            Conditions=[
                *({name: value} for name, value in fields.items()),
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=60 * valid_for_min,
        )

        return PresignedPost(
            object_key=key,
            object_url=f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{key}",
            url=response["url"],
            fields=dict(response["fields"]),
            max_bytes=max_bytes,
        )

    def verify_uploads(
        self,
        references: Iterable[str | None],
        attached: Iterable[str | None] = (),
    ) -> None:
        keys = {uploaded_object_key(reference) for reference in references}
        keys -= {uploaded_object_key(reference) for reference in attached}
        keys.discard(None)
        for key in sorted(keys):
            self.verify_upload(key)

    def verify_upload(self, key: str) -> None:
        try:
            response = aws_utils.create_client("s3").get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=key,
                Range=f"bytes=0-{_SIGNATURE_BYTES - 1}",
            )
            body = response["Body"]
            try:
                leading_bytes = body.read(_SIGNATURE_BYTES)
            finally:
                body.close()
        except (BotoCoreError, ClientError) as e:
            logger.warning("Could not read uploaded object %r: %s", key, e)
            raise UploadVerificationError(
                "The uploaded file could not be verified."
            ) from e

        content_type = response.get("ContentType", "")
        signature = CONTENT_SIGNATURES.get(content_type)
        if signature is None or not leading_bytes.startswith(signature):
            raise UploadVerificationError("The uploaded file does not match its type.")

        size = int(response["ContentRange"].rpartition("/")[2])
        if size > MAX_UPLOAD_BYTES[content_type]:
            raise UploadVerificationError("The uploaded file is too large.")

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

    def _new_upload_key(
        self, entity: str, filename: str, user_id: str, content_type: str
    ) -> str:
        if entity not in SUPPORTED_ENTITIES:
            raise ValueError(f"Unsupported entity: {entity}")

        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(f"Unsupported content type: {content_type}")

        key_filename = self._key_filename(filename, content_type)
        return f"uploads/{entity}s/users/{user_id}/{uuid.uuid4()}/{key_filename}"

    def _key_filename(self, filename: str, content_type: str) -> str:
        extensions = SUPPORTED_CONTENT_TYPE_EXTENSIONS[content_type]
        stem, _, extension = filename.rpartition(".")
        if stem and extension.lower() in extensions:
            return filename
        return f"{filename.strip('.') or 'file'}.{extensions[0]}"

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for the S3 metadata `file-name` field.

        See: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        """
        name = unicodedata.normalize("NFKD", filename)
        name = name.encode("ascii", "ignore").decode("ascii")
        name = quote(name, safe="!-_.*'()")
        return name
