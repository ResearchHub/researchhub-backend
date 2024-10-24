import uuid

from boto3 import session

from researchhub import settings


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
    ) -> str:
        """
        Create a presigned URL for uploading a file to S3 that is time-limited.
        """

        s3_filename = f"/uploads/{user_id}/{uuid.uuid4()}/{filename}"

        boto3_session = session.Session()
        s3_client = boto3_session.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

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

        return url
