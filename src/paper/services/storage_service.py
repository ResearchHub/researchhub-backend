import uuid
from typing import NamedTuple

from researchhub import settings
from utils import aws as aws_utils


class PresignedUrl(NamedTuple):
    object_key: str
    url: str


class StorageService:
    """
    Service for interacting with S3 storage.
    """

    def create_presigned_url(
        self,
        filename: str,
        user_id: str,
        content_type: str = "application/pdf",
        valid_for: int = 2,
    ) -> PresignedUrl:
        """
        Create a presigned URL for uploading a file to S3 that is time-limited.
        """

        s3_filename = f"uploads/papers/users/{user_id}/{uuid.uuid4()}/{filename}"

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
            ExpiresIn=60 * valid_for,
        )

        return PresignedUrl(url=url, object_key=s3_filename)
