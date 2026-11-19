import base64
import io
import json
import uuid
from unittest.mock import Mock, patch

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from django.conf import settings
from django.test import TestCase, override_settings

from researchhub.services import storage_service
from researchhub.services.storage_service import (
    MAX_UPLOAD_BYTES,
    S3StorageService,
    UploadVerificationError,
    uploaded_object_key,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n"
UPLOAD_KEY = "uploads/posts/users/1/abc/cover.png"


def stored_object(
    content=PNG_BYTES, content_type="image/png", size=None
) -> dict[str, object]:
    total = len(content) if size is None else size
    return {
        "Body": io.BytesIO(content),
        "ContentRange": f"bytes 0-{len(content) - 1}/{total}",
        "ContentType": content_type,
    }


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

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_create_presigned_url_key_extension_matches_content_type(
        self, create_client_mock
    ):
        cases = [
            ("page.html", "image/png", "page.html.png"),
            ("image.svg", "image/jpeg", "image.svg.jpg"),
            ("paper", "application/pdf", "paper.pdf"),
            (".html", "image/png", "html.png"),
            ("photo.jpeg", "image/jpeg", "photo.jpeg"),
            ("photo.JPG", "image/jpeg", "photo.JPG"),
            ("photo.png", "image/jpeg", "photo.png.jpg"),
        ]
        for filename, content_type, expected in cases:
            with self.subTest(filename=filename, content_type=content_type):
                # Arrange
                s3_client_mock = Mock()
                s3_client_mock.generate_presigned_url.return_value = "https://url1"
                create_client_mock.return_value = s3_client_mock

                # Act
                url = S3StorageService().create_presigned_url(
                    "post", filename, "userId1", content_type
                )

                # Assert
                signed = s3_client_mock.generate_presigned_url.call_args.kwargs
                self.assertEqual(signed["Params"]["Key"], url.object_key)
                self.assertEqual(signed["Params"]["ContentType"], content_type)
                self.assertEqual(url.object_key.rsplit("/", 1)[-1], expected)
                self.assertTrue(url.object_url.endswith(f"/{expected}"))

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

    def test_object_key_from_url(self):
        # Act & Assert
        self.assertEqual(
            storage_service.object_key_from_url(
                "https://storage.test.researchhub.com/uploads/papers/users/1/abc/file1.pdf"
            ),
            "uploads/papers/users/1/abc/file1.pdf",
        )
        self.assertEqual(
            storage_service.object_key_from_url(
                "https://storage.test.researchhub.com/uploads/papers/my file.pdf"
            ),
            "uploads/papers/my file.pdf",
        )

    def test_object_key_from_url_keeps_url_delimiters_in_filename(self):
        # Object URLs hold the raw key, so `;`, `?` and `#` are part of the filename
        for filename in ["a;b.pdf", "a?b.pdf", "a#b.pdf", "a%20b.pdf"]:
            with self.subTest(filename=filename):
                # Act
                key = storage_service.object_key_from_url(
                    f"https://storage.test.researchhub.com/uploads/papers/{filename}"
                )

                # Assert
                self.assertEqual(key, f"uploads/papers/{filename}")

    def test_object_key_from_url_returns_none_for_other_hosts(self):
        # Act & Assert
        self.assertIsNone(
            storage_service.object_key_from_url("https://arxiv.org/pdf/2101.00001")
        )
        self.assertIsNone(
            storage_service.object_key_from_url(
                "https://storage.test.researchhub.com.evil.com/uploads/file1.pdf"
            )
        )
        self.assertIsNone(storage_service.object_key_from_url(None))
        self.assertIsNone(storage_service.object_key_from_url(""))
        self.assertIsNone(
            storage_service.object_key_from_url("https://storage.test.researchhub.com/")
        )

    @override_settings(AWS_S3_CUSTOM_DOMAIN="https://storage.test.researchhub.com")
    def test_object_key_from_url_with_scheme_in_domain_setting(self):
        # Act
        key = storage_service.object_key_from_url(
            "https://storage.test.researchhub.com/uploads/papers/file1.pdf"
        )

        # Assert
        self.assertEqual(key, "uploads/papers/file1.pdf")

    @override_settings(AWS_S3_CUSTOM_DOMAIN="")
    def test_object_key_from_url_returns_none_without_domain_setting(self):
        # Act & Assert
        self.assertIsNone(storage_service.object_key_from_url("/uploads/file1.pdf"))
        self.assertIsNone(
            storage_service.object_key_from_url(
                "https://storage.test.researchhub.com/uploads/file1.pdf"
            )
        )

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


@override_settings(AWS_STORAGE_BUCKET_NAME="test-bucket")
@override_settings(AWS_S3_CUSTOM_DOMAIN="storage.test.researchhub.com")
class PresignedPostTest(TestCase):
    @patch("researchhub.services.storage_service.aws_utils.create_client")
    @patch("researchhub.services.storage_service.uuid.uuid4")
    def test_create_presigned_post(self, uuid_mock, create_client_mock):
        # Arrange
        uuid_mock.return_value = "uuid1"
        s3_client_mock = create_client_mock.return_value
        s3_client_mock.generate_presigned_post.return_value = {
            "url": "https://test-bucket.s3.amazonaws.com/",
            "fields": {"key": "signed-key", "policy": "signed-policy"},
        }

        # Act
        upload = S3StorageService().create_presigned_post(
            "post", "cover.png", 7, "image/png", valid_for_min=3
        )

        # Assert
        key = "uploads/posts/users/7/uuid1/cover.png"
        fields = {
            "Content-Type": "image/png",
            "x-amz-meta-created-by-id": "7",
            "x-amz-meta-file-name": "cover.png",
        }
        s3_client_mock.generate_presigned_post.assert_called_once_with(
            Bucket="test-bucket",
            Key=key,
            Fields=fields,
            Conditions=[
                {"Content-Type": "image/png"},
                {"x-amz-meta-created-by-id": "7"},
                {"x-amz-meta-file-name": "cover.png"},
                ["content-length-range", 1, MAX_UPLOAD_BYTES["image/png"]],
            ],
            ExpiresIn=180,
        )
        self.assertEqual(upload.object_key, key)
        self.assertEqual(
            upload.object_url, f"https://storage.test.researchhub.com/{key}"
        )
        self.assertEqual(upload.url, "https://test-bucket.s3.amazonaws.com/")
        self.assertEqual(
            upload.fields, {"key": "signed-key", "policy": "signed-policy"}
        )
        self.assertEqual(upload.max_bytes, MAX_UPLOAD_BYTES["image/png"])

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_signed_policy_fixes_key_type_and_size(self, create_client_mock):
        # Arrange
        create_client_mock.return_value = boto3.Session(
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name="us-west-2",
        ).client("s3")

        # Act
        upload = S3StorageService().create_presigned_post(
            "comment", "scan.pdf", 7, "application/pdf"
        )

        # Assert
        policy = json.loads(base64.b64decode(upload.fields["policy"]))
        self.assertCountEqual(
            policy["conditions"],
            [
                {"Content-Type": "application/pdf"},
                {"x-amz-meta-created-by-id": "7"},
                {"x-amz-meta-file-name": "scan.pdf"},
                ["content-length-range", 1, MAX_UPLOAD_BYTES["application/pdf"]],
                {"bucket": "test-bucket"},
                {"key": upload.object_key},
            ],
        )
        self.assertEqual(upload.fields["Content-Type"], "application/pdf")
        self.assertEqual(upload.fields["key"], upload.object_key)

    @patch("researchhub.services.storage_service.aws_utils.create_client")
    def test_create_presigned_post_key_extension_matches_type(self, create_client_mock):
        # Arrange
        create_client_mock.return_value.generate_presigned_post.return_value = {
            "url": "https://test-bucket.s3.amazonaws.com/",
            "fields": {},
        }

        # Act
        upload = S3StorageService().create_presigned_post(
            "note", "page.html", 7, "image/png"
        )

        # Assert
        self.assertTrue(upload.object_key.endswith("/page.html.png"))

    def test_create_presigned_post_rejects_unsupported_values(self):
        # Arrange
        service = S3StorageService()

        # Act & Assert
        with self.assertRaises(ValueError):
            service.create_presigned_post("user", "a.png", 7, "image/png")
        with self.assertRaises(ValueError):
            service.create_presigned_post("post", "a.html", 7, "text/html")


@override_settings(AWS_STORAGE_BUCKET_NAME="test-bucket")
@override_settings(AWS_S3_CUSTOM_DOMAIN="storage.test.researchhub.com")
@patch("researchhub.services.storage_service.aws_utils.create_client")
class VerifyUploadTest(TestCase):
    def test_accepts_objects_matching_their_type(self, create_client_mock):
        # Arrange
        cases = {
            "application/pdf": b"%PDF-1.7",
            "image/jpeg": b"\xff\xd8\xff\xe0",
            "image/png": PNG_BYTES,
        }
        s3_client_mock = create_client_mock.return_value

        for content_type, content in cases.items():
            with self.subTest(content_type=content_type):
                s3_client_mock.get_object.return_value = stored_object(
                    content, content_type, MAX_UPLOAD_BYTES[content_type]
                )

                # Act & Assert
                S3StorageService().verify_upload(UPLOAD_KEY)

    def test_reads_only_the_leading_bytes(self, create_client_mock):
        # Arrange
        s3_client_mock = create_client_mock.return_value
        stored = stored_object()
        s3_client_mock.get_object.return_value = stored

        # Act
        S3StorageService().verify_upload(UPLOAD_KEY)

        # Assert
        s3_client_mock.get_object.assert_called_once_with(
            Bucket="test-bucket", Key=UPLOAD_KEY, Range="bytes=0-7"
        )
        self.assertTrue(stored["Body"].closed)

    def test_rejects_bytes_of_another_type(self, create_client_mock):
        # Arrange
        create_client_mock.return_value.get_object.return_value = stored_object(
            b"<html><script>"
        )

        # Act & Assert
        with self.assertRaisesMessage(UploadVerificationError, "does not match"):
            S3StorageService().verify_upload(UPLOAD_KEY)

    def test_rejects_stored_type_outside_allow_list(self, create_client_mock):
        # Arrange
        create_client_mock.return_value.get_object.return_value = stored_object(
            PNG_BYTES, "text/html"
        )

        # Act & Assert
        with self.assertRaisesMessage(UploadVerificationError, "does not match"):
            S3StorageService().verify_upload(UPLOAD_KEY)

    def test_rejects_object_over_the_type_limit(self, create_client_mock):
        # Arrange
        create_client_mock.return_value.get_object.return_value = stored_object(
            size=MAX_UPLOAD_BYTES["image/png"] + 1
        )

        # Act & Assert
        with self.assertRaisesMessage(UploadVerificationError, "too large"):
            S3StorageService().verify_upload(UPLOAD_KEY)

    def test_rejects_object_that_cannot_be_read(self, create_client_mock):
        # Arrange
        errors = [
            ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"),
            ClientError({"Error": {"Code": "InvalidRange"}}, "GetObject"),
            EndpointConnectionError(endpoint_url="https://s3.test"),
        ]
        s3_client_mock = create_client_mock.return_value

        for error in errors:
            with self.subTest(error=type(error).__name__):
                s3_client_mock.get_object.side_effect = error

                # Act & Assert
                with self.assertRaisesMessage(
                    UploadVerificationError, "could not be verified"
                ):
                    S3StorageService().verify_upload(UPLOAD_KEY)

    def test_verify_uploads_ignores_other_references(self, create_client_mock):
        # Arrange
        references = [
            None,
            "",
            7,
            ["uploads/posts/users/1/abc/cover.png"],
            "notes/cover.png",
            "/imagePath1",
            "https://example.com/uploads/posts/users/1/abc/cover.png",
        ]

        # Act
        S3StorageService().verify_uploads(references)

        # Assert
        create_client_mock.assert_not_called()

    def test_verify_uploads_checks_a_key_and_its_url_once(self, create_client_mock):
        # Arrange
        s3_client_mock = create_client_mock.return_value
        s3_client_mock.get_object.return_value = stored_object()

        # Act
        S3StorageService().verify_uploads(
            [UPLOAD_KEY, f"https://storage.test.researchhub.com/{UPLOAD_KEY}"]
        )

        # Assert
        s3_client_mock.get_object.assert_called_once()
        self.assertEqual(s3_client_mock.get_object.call_args.kwargs["Key"], UPLOAD_KEY)

    def test_verify_uploads_skips_already_attached_keys(self, create_client_mock):
        # Act
        S3StorageService().verify_uploads(
            [UPLOAD_KEY, f"https://storage.test.researchhub.com/{UPLOAD_KEY}"],
            attached=[UPLOAD_KEY],
        )

        # Assert
        create_client_mock.assert_not_called()

    def test_uploaded_object_key_resolves_equivalent_spellings(
        self, create_client_mock
    ):
        # Arrange
        references = [
            UPLOAD_KEY,
            f"/{UPLOAD_KEY}",
            f"./{UPLOAD_KEY}",
            f"other/../{UPLOAD_KEY}",
            UPLOAD_KEY.replace("/", "\\"),
            UPLOAD_KEY.replace("/posts/", "//posts/"),
            f"x://../{UPLOAD_KEY}",
            f"https://storage.test.researchhub.com/{UPLOAD_KEY}",
            "https://STORAGE.test.researchhub.com/%75ploads/posts/users/1/abc/cover.png",
        ]

        for reference in references:
            with self.subTest(reference=reference):
                # Act
                key = uploaded_object_key(reference)

                # Assert
                self.assertEqual(key, UPLOAD_KEY)
