import io
from unittest import TestCase
from unittest.mock import Mock

from botocore.exceptions import ClientError

from researchhub.services.private_storage_service import (
    ObjectsNotDeletedError,
    PresignedPost,
    PrivateStorageNotConfiguredError,
    PrivateStorageService,
    StoredObject,
)

BUCKET = "researchhub-test-private-storage"


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "HeadObject")


class PrivateStorageServiceTests(TestCase):
    def setUp(self):
        self.client = Mock()
        self.service = PrivateStorageService(client=self.client, bucket=BUCKET)

    def test_presigned_post_pins_the_type_and_bounds_the_size(self):
        # Arrange
        self.client.generate_presigned_post.return_value = {
            "url": "https://bucket.s3.amazonaws.com/",
            "fields": {"key": "uploads/a.pdf", "policy": "p"},
        }

        # Act
        upload = self.service.presigned_post(
            "uploads/a.pdf",
            content_type="application/pdf",
            max_bytes=1024,
            expires_in=600,
        )

        # Assert
        self.client.generate_presigned_post.assert_called_once_with(
            Bucket=BUCKET,
            Key="uploads/a.pdf",
            Fields={"Content-Type": "application/pdf"},
            Conditions=[
                {"Content-Type": "application/pdf"},
                ["content-length-range", 1, 1024],
            ],
            ExpiresIn=600,
        )
        self.assertEqual(
            upload,
            PresignedPost(
                url="https://bucket.s3.amazonaws.com/",
                fields={"key": "uploads/a.pdf", "policy": "p"},
            ),
        )

    def test_head_reports_a_missing_object_as_none(self):
        # Arrange
        self.client.head_object.side_effect = _client_error("404")

        # Act / Assert
        self.assertIsNone(self.service.head("uploads/missing.pdf"))

    def test_head_raises_other_errors(self):
        # Arrange
        self.client.head_object.side_effect = _client_error("403")

        # Act / Assert
        with self.assertRaises(ClientError):
            self.service.head("uploads/forbidden.pdf")

    def test_head_returns_size_and_type(self):
        # Arrange
        self.client.head_object.return_value = {
            "ContentLength": 42,
            "ContentType": "application/pdf",
            "ETag": '"abc"',
        }

        # Act
        stored = self.service.head("uploads/a.pdf")

        # Assert
        self.assertEqual(stored, StoredObject(42, "application/pdf", '"abc"'))

    def test_read_refuses_an_object_over_the_limit(self):
        # Arrange
        self.client.get_object.side_effect = lambda **_: {"Body": io.BytesIO(b"x" * 11)}

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.read("uploads/big.pdf", max_bytes=10)
        self.assertEqual(self.service.read("uploads/big.pdf", max_bytes=11), b"x" * 11)

    def test_read_can_require_the_object_to_be_unchanged(self):
        # Arrange
        self.client.get_object.side_effect = lambda **_: {"Body": io.BytesIO(b"x")}

        # Act
        self.service.read("uploads/a.pdf", max_bytes=10)
        self.service.read("uploads/a.pdf", max_bytes=10, if_match='"abc"')

        # Assert
        unconditional, conditional = self.client.get_object.call_args_list
        self.assertNotIn("IfMatch", unconditional.kwargs)
        self.assertEqual(conditional.kwargs["IfMatch"], '"abc"')

    def test_presigned_get_names_the_download(self):
        # Arrange
        self.client.generate_presigned_url.return_value = "https://signed"

        # Act
        url = self.service.presigned_get(
            "uploads/a.pdf", filename="Grant draft é.pdf", expires_in=300
        )

        # Assert
        self.assertEqual(url, "https://signed")
        self.client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": BUCKET,
                "Key": "uploads/a.pdf",
                "ResponseContentDisposition": (
                    "inline; filename*=UTF-8''Grant%20draft%20%C3%A9.pdf"
                ),
            },
            ExpiresIn=300,
        )

    def test_write_stores_the_bytes_under_their_type(self):
        # Act
        self.service.write("uploads/a/pages/1.jpg", b"jpeg", content_type="image/jpeg")

        # Assert
        self.client.put_object.assert_called_once_with(
            Bucket=BUCKET,
            Key="uploads/a/pages/1.jpg",
            Body=b"jpeg",
            ContentType="image/jpeg",
        )

    def test_delete_many_sends_as_many_keys_as_one_request_takes(self):
        # Arrange
        self.client.delete_objects.return_value = {}
        keys = [f"uploads/a/pages/{page}.jpg" for page in range(1, 2002)]

        # Act
        self.service.delete_many(keys)

        # Assert
        sent = [
            [entry["Key"] for entry in request.kwargs["Delete"]["Objects"]]
            for request in self.client.delete_objects.call_args_list
        ]
        self.assertEqual([len(batch) for batch in sent], [1000, 1000, 1])
        self.assertEqual([key for batch in sent for key in batch], keys)
        for request in self.client.delete_objects.call_args_list:
            self.assertEqual(request.kwargs["Bucket"], BUCKET)

    def test_delete_many_of_nothing_sends_nothing(self):
        # Act
        self.service.delete_many([])

        # Assert
        self.client.delete_objects.assert_not_called()

    def test_delete_many_raises_when_a_key_is_not_deleted(self):
        # Arrange: S3 answers 200 and lists the keys it kept.
        self.client.delete_objects.return_value = {
            "Errors": [{"Key": "uploads/a/pages/2.jpg", "Code": "AccessDenied"}]
        }

        # Act / Assert
        with self.assertRaises(ObjectsNotDeletedError):
            self.service.delete_many(["uploads/a/pages/1.jpg", "uploads/a/pages/2.jpg"])

    def test_an_unset_bucket_is_not_configured(self):
        # Arrange
        service = PrivateStorageService(client=self.client, bucket="")

        # Act / Assert
        self.assertFalse(service.configured)
        with self.assertRaises(PrivateStorageNotConfiguredError):
            service.delete("uploads/a.pdf")
        with self.assertRaises(PrivateStorageNotConfiguredError):
            service.delete_many(["uploads/a.pdf"])
        self.client.delete_object.assert_not_called()
        self.client.delete_objects.assert_not_called()
