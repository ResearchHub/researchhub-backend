import uuid
from unittest import TestCase
from unittest.mock import Mock, patch

from django.conf import settings

from paper.services import storage_service
from paper.services.storage_service import StorageService


class StorageServiceTest(TestCase):

    @patch("paper.services.storage_service.aws_utils.create_client")
    @patch("paper.services.storage_service.uuid.uuid4")
    def test_create_presigned_url(self, mock_uuid, mock_create_client):
        # Arrange
        uuid1 = uuid.uuid4()
        mock_uuid.return_value = uuid1

        mock_s3_client = Mock()
        mock_create_client.return_value = mock_s3_client

        mock_s3_client.generate_presigned_url.return_value = "https://presignedUrl1"

        service = StorageService()

        # Act
        url = service.create_presigned_url("file1.pdf", "userId1", valid_for=2)

        # Assert
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": f"uploads/papers/users/userId1/{uuid1}/file1.pdf",
                "ContentType": "application/pdf",
                "Metadata": {
                    "created-by-id": "userId1",
                    "file-name": "file1.pdf",
                },
            },
            ExpiresIn=60 * 2,
        )

        self.assertEqual(
            url,
            storage_service.PresignedUrl(
                url="https://presignedUrl1",
                object_key=f"uploads/papers/users/userId1/{uuid1}/file1.pdf",
            ),
        )
