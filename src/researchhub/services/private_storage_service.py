"""S3 access to the private bucket, for user uploads that must never be public.

Objects there have no public address: browsers upload and download them only
through short-lived presigned requests issued here.
"""

from dataclasses import dataclass
from urllib.parse import quote

from botocore.exceptions import ClientError
from django.conf import settings

from utils import aws as aws_utils

_MISSING_OBJECT_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class PrivateStorageNotConfiguredError(RuntimeError):
    """``AWS_PRIVATE_STORAGE_BUCKET_NAME`` is unset in this deployment."""


@dataclass(frozen=True)
class PresignedPost:
    """A browser form upload: POST ``fields``, then the file, to ``url``."""

    url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class StoredObject:
    size_bytes: int
    content_type: str
    # Changes whenever the object is overwritten.
    etag: str = ""


class PrivateStorageService:
    """Presigned uploads/downloads and server-side reads for the private bucket."""

    def __init__(self, *, client=None, bucket: str | None = None):
        self._client = client
        self._bucket = bucket

    @property
    def configured(self) -> bool:
        return bool(self._bucket_name())

    @property
    def bucket(self) -> str:
        bucket = self._bucket_name()
        if not bucket:
            raise PrivateStorageNotConfiguredError(
                "AWS_PRIVATE_STORAGE_BUCKET_NAME is not configured"
            )
        return bucket

    def presigned_post(
        self, key: str, *, content_type: str, max_bytes: int, expires_in: int
    ) -> PresignedPost:
        """A form upload to ``key`` that S3 rejects unless the body is 1 to
        ``max_bytes`` bytes and declared as ``content_type``."""
        response = self._s3().generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=expires_in,
        )
        return PresignedPost(url=response["url"], fields=dict(response["fields"]))

    def head(self, key: str) -> StoredObject | None:
        """The stored object's metadata, or ``None`` when nothing is at ``key``."""
        try:
            response = self._s3().head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
                return None
            raise
        return StoredObject(
            size_bytes=int(response["ContentLength"]),
            content_type=response.get("ContentType", ""),
            etag=response.get("ETag", ""),
        )

    def read(self, key: str, *, max_bytes: int, if_match: str = "") -> bytes:
        """The object's bytes; raises ``ValueError`` past ``max_bytes``.

        With ``if_match``, S3 refuses the read unless the object still has
        that ETag.
        """
        params = {"Bucket": self.bucket, "Key": key}
        if if_match:
            params["IfMatch"] = if_match
        body = self._s3().get_object(**params)["Body"]
        try:
            data = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise ValueError(f"object exceeds {max_bytes} bytes")
        return data

    def presigned_get(self, key: str, *, filename: str, expires_in: int) -> str:
        """A short-lived download URL that names the file ``filename``."""
        return self._s3().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": (
                    f"inline; filename*=UTF-8''{quote(filename, safe='')}"
                ),
            },
            ExpiresIn=expires_in,
        )

    def delete(self, key: str) -> None:
        self._s3().delete_object(Bucket=self.bucket, Key=key)

    def _bucket_name(self) -> str:
        if self._bucket is not None:
            return self._bucket
        return settings.AWS_PRIVATE_STORAGE_BUCKET_NAME

    def _s3(self):
        if self._client is None:
            self._client = aws_utils.create_client("s3")
        return self._client
