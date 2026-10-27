import uuid
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, NoRegionError
from django.conf import settings
from django.test import TestCase, override_settings

from researchhub.services import storage_service
from researchhub.services.storage_service import S3StorageService


@override_settings(AWS_STORAGE_BUCKET_NAME="test-bucket")
@override_settings(AWS_S3_CUSTOM_DOMAIN="storage.test.researchhub.com")
class StorageServiceTest(TestCase):
    @patch("researchhub.services.storage_service.aws_utils.create_client")
    @patch("researchhub.services.storage_service.uuid.uuid4")
    def test_create_presigned_url(self, uuid_mock, create_client_mock):
        # Arrange
        uuid1 = uuid.uuid4()
        uuid_mock.return_value = uuid1

        s3_client_mock = Mock()
        create_client_mock.return_value = s3_client_mock

        s3_client_mock.generate_presigned_url.return_value = "https://presignedUrl1"

        service = S3StorageService()

        # Act
        url = service.create_presigned_url(
            "paper", "file1.pdf", "userId1", "application/pdf", valid_for_min=3
        )

        # Assert
        s3_client_mock.generate_presigned_url.assert_called_once_with(
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

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_quarantine_object(self, create_client_mock):
        # Arrange
        s3_client_mock = Mock()
        create_client_mock.return_value = s3_client_mock
        key = "uploads/papers/2024/01/01/file1.pdf"

        # Act
        new_key = S3StorageService().quarantine_object(key)

        # Assert
        self.assertEqual(new_key, f"quarantine/{key}")
        s3_client_mock.copy_object.assert_called_once_with(
            Bucket="test-bucket",
            CopySource={"Bucket": "test-bucket", "Key": key},
            Key=f"quarantine/{key}",
        )
        s3_client_mock.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key=key
        )

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_quarantine_object_returns_none_on_s3_error(self, create_client_mock):
        # Arrange
        s3_client_mock = Mock()
        s3_client_mock.copy_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}}, "CopyObject"
        )
        create_client_mock.return_value = s3_client_mock

        # Act
        result = S3StorageService().quarantine_object("uploads/papers/file1.pdf")

        # Assert
        self.assertIsNone(result)
        s3_client_mock.delete_object.assert_not_called()

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_quarantine_object_returns_none_when_source_missing(
        self, create_client_mock
    ):
        # Arrange
        s3_client_mock = Mock()
        s3_client_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        create_client_mock.return_value = s3_client_mock

        # Act
        result = S3StorageService().quarantine_object("uploads/papers/file1.pdf")

        # Assert
        self.assertIsNone(result)
        s3_client_mock.copy_object.assert_not_called()
        s3_client_mock.delete_object.assert_not_called()

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_move_object_raises_on_unexpected_head_error(self, create_client_mock):
        # Arrange
        s3_client_mock = Mock()
        s3_client_mock.head_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "HeadObject"
        )
        create_client_mock.return_value = s3_client_mock

        # Act & Assert
        with self.assertRaises(ClientError):
            S3StorageService().restore_object("uploads/papers/file1.pdf")
        s3_client_mock.copy_object.assert_not_called()

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_restore_object(self, create_client_mock):
        # Arrange
        s3_client_mock = Mock()
        create_client_mock.return_value = s3_client_mock
        key = "uploads/papers/2024/01/01/file1.pdf"

        # Act
        restored_key = S3StorageService().restore_object(key)

        # Assert
        self.assertEqual(restored_key, key)
        s3_client_mock.copy_object.assert_called_once_with(
            Bucket="test-bucket",
            CopySource={"Bucket": "test-bucket", "Key": f"quarantine/{key}"},
            Key=key,
        )
        s3_client_mock.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key=f"quarantine/{key}"
        )

    @override_settings(AWS_STORAGE_CDN_DISTRIBUTION_ID="distribution1")
    @patch("researchhub.services.storage_service.uuid.uuid4")
    def test_invalidate_cdn_cache(self, uuid_mock):
        # Arrange
        uuid_mock.return_value = "reference1"
        cloudfront_client_mock = Mock()
        keys = [
            "uploads/papers/users/1/paper1.pdf",
            "uploads/posts/users/1/post1.txt",
            "uploads/posts/users/1/post1.txt",
        ]

        # Act
        S3StorageService(cloudfront_client_mock).invalidate_cdn_cache(keys)

        # Assert
        cloudfront_client_mock.create_invalidation.assert_called_once_with(
            DistributionId="distribution1",
            InvalidationBatch={
                "Paths": {
                    "Quantity": 2,
                    "Items": [
                        "/uploads/papers/users/1/paper1.pdf",
                        "/uploads/posts/users/1/post1.txt",
                    ],
                },
                "CallerReference": "reference1",
            },
        )

    @override_settings(AWS_STORAGE_CDN_DISTRIBUTION_ID="distribution1")
    def test_invalidate_cdn_cache_path_encoding(self):
        # Arrange
        cloudfront_client_mock = Mock()
        keys = [
            "uploads/a b.pdf",
            "uploads/a&b=c@d+e.pdf",
            "uploads/caf\u00e9.pdf",
            "uploads/1/notes~v2.pdf",
        ]

        # Act
        S3StorageService(cloudfront_client_mock).invalidate_cdn_cache(keys)

        # Assert
        (call,) = cloudfront_client_mock.create_invalidation.mock_calls
        self.assertEqual(
            call.kwargs["InvalidationBatch"]["Paths"]["Items"],
            [
                "/uploads/1/notes*",
                "/uploads/a%20b.pdf",
                "/uploads/a&b=c@d+e.pdf",
                "/uploads/caf%C3%A9.pdf",
            ],
        )

    @override_settings(AWS_STORAGE_CDN_DISTRIBUTION_ID="distribution1")
    @patch.object(storage_service, "CDN_INVALIDATION_BATCH_SIZE", 2)
    def test_invalidate_cdn_cache_in_batches(self):
        # Arrange
        cloudfront_client_mock = Mock()
        keys = ["file1.pdf", "file2.pdf", "file3.pdf"]

        # Act
        S3StorageService(cloudfront_client_mock).invalidate_cdn_cache(keys)

        # Assert
        batches = [
            call.kwargs["InvalidationBatch"]["Paths"]["Items"]
            for call in cloudfront_client_mock.create_invalidation.mock_calls
        ]
        self.assertEqual(batches, [["/file1.pdf", "/file2.pdf"], ["/file3.pdf"]])

    @override_settings(AWS_STORAGE_CDN_DISTRIBUTION_ID="distribution1")
    @patch.object(storage_service, "CDN_INVALIDATION_BATCH_SIZE", 1)
    def test_invalidate_cdn_cache_logs_failed_batch(self):
        # Arrange
        cloudfront_client_mock = Mock()
        cloudfront_client_mock.create_invalidation.side_effect = [
            ClientError(
                {"Error": {"Code": "TooManyInvalidationsInProgress"}},
                "CreateInvalidation",
            ),
            {},
        ]
        service = S3StorageService(cloudfront_client_mock)

        # Act
        with self.assertLogs(storage_service.logger, level="ERROR") as logs:
            service.invalidate_cdn_cache(["file1.pdf", "file2.pdf"])

        # Assert
        self.assertEqual(cloudfront_client_mock.create_invalidation.call_count, 2)
        self.assertIn("Failed to invalidate 1 CDN paths", logs.output[0])

    @override_settings(AWS_STORAGE_CDN_DISTRIBUTION_ID="distribution1")
    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_invalidate_cdn_cache_logs_client_creation_failure(
        self, create_client_mock
    ):
        # Arrange
        create_client_mock.side_effect = NoRegionError()

        # Act
        with self.assertLogs(storage_service.logger, level="ERROR") as logs:
            S3StorageService().invalidate_cdn_cache(["file1.pdf"])

        # Assert
        create_client_mock.assert_called_once_with("cloudfront")
        self.assertIn("Failed to create CloudFront client", logs.output[0])

    @override_settings(AWS_STORAGE_CDN_DISTRIBUTION_ID="")
    def test_invalidate_cdn_cache_skipped_without_distribution(self):
        # Arrange
        cloudfront_client_mock = Mock()

        # Act
        S3StorageService(cloudfront_client_mock).invalidate_cdn_cache(["file1.pdf"])

        # Assert
        cloudfront_client_mock.create_invalidation.assert_not_called()

    @override_settings(AWS_STORAGE_CDN_DISTRIBUTION_ID="distribution1")
    def test_invalidate_cdn_cache_skipped_without_keys(self):
        # Arrange
        cloudfront_client_mock = Mock()

        # Act
        S3StorageService(cloudfront_client_mock).invalidate_cdn_cache([])

        # Assert
        cloudfront_client_mock.create_invalidation.assert_not_called()
