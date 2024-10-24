import uuid
from unittest import TestCase
from unittest.mock import Mock, patch

from paper.services.storage_service import StorageService
from researchhub import settings


class StorageServiceTest(TestCase):

    @patch("paper.services.storage_service.session.Session")
    @patch("paper.services.storage_service.uuid.uuid4")
    def test_create_presigned_url(self, mock_uuid, mock_session):
        # Arrange
        uuid1 = uuid.uuid4()
        mock_uuid.return_value = uuid1

        mock_s3_client = Mock()
        mock_session.return_value.client.return_value = mock_s3_client

        mock_s3_client.generate_presigned_url.return_value = "https://presignedUrl1"

        service = StorageService()

        # Act
        url = service.create_presigned_url("file1.pdf", "userId1", valid_for=2)

        # Assert
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": f"/uploads/userId1/{uuid1}/file1.pdf",
                "ContentType": "application/pdf",
                "Metadata": {
                    "created-by-id": "userId1",
                    "file-name": "file1.pdf",
                },
            },
            ExpiresIn=60 * 2,
        )

        self.assertEqual(url, "https://presignedUrl1")
