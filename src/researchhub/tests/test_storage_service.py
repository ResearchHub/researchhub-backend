import uuid
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from researchhub.services import storage_service
from researchhub.services.storage_service import S3StorageService


@override_settings(AWS_S3_CUSTOM_DOMAIN="storage.test.researchhub.com")
class StorageServiceTest(TestCase):

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    @patch("researchhub.services.storage_service.uuid.uuid4")
    def test_create_presigned_url(self, mock_uuid, mock_create_client):
        # Arrange
        uuid1 = uuid.uuid4()
        mock_uuid.return_value = uuid1

        mock_s3_client = Mock()
        mock_create_client.return_value = mock_s3_client

        mock_s3_client.generate_presigned_url.return_value = "https://presignedUrl1"

        service = S3StorageService()

        # Act
        url = service.create_presigned_url(
            "paper", "file1.pdf", "userId1", "application/pdf", valid_for_min=3
        )

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
            ExpiresIn=60 * 3,
        )

        self.assertEqual(
            url,
            storage_service.PresignedUrl(
                url="https://presignedUrl1",
                object_key=f"uploads/papers/users/userId1/{uuid1}/file1.pdf",
                object_url=f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/uploads/papers/users/userId1/{uuid1}/file1.pdf",
            ),
        )

    def test_create_presigned_url_unsupported_entity(self):
        with self.assertRaises(ValueError):
            S3StorageService().create_presigned_url(
                "UNSUPPORTED",
                "file1.pdf",
                "userId1",
                "application/pdf",
                valid_for_min=3,
            )

    def test_create_presigned_url_unsupported_content_type(self):
        with self.assertRaises(ValueError):
            S3StorageService().create_presigned_url(
                "paper", "file1.pdf", "userId1", "UNSUPPORTED", valid_for_min=3
            )

    def test_sanitize_filename(self):
        # Arrange
        s = S3StorageService()

        # Act & Assert
        self.assertEqual(s._sanitize_filename("file1.pdf"), "file1.pdf")
        self.assertEqual(s._sanitize_filename("f(|@äöü).pdf"), "f(%7C%40aou).pdf")
        self.assertEqual(s._sanitize_filename("Żurowski.pdf"), "Zurowski.pdf")
