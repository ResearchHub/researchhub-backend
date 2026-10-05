import io
from unittest import TestCase
from unittest.mock import Mock

from botocore.exceptions import ClientError

from research_ai.services.agent.images import ImageUnavailableError
from research_ai.services.agent_files import image_loader
from research_ai.services.agent_files.image_loader import PrivateStorageImageLoader
from researchhub.services.private_storage_service import PrivateStorageService

BUCKET = "researchhub-test-private-storage"
KEY = "uploads/research_ai/users/1/abc/pages/3.jpg"


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "GetObject")


class PrivateStorageImageLoaderTests(TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get_object.side_effect = lambda **kwargs: {
            "Body": io.BytesIO(b"jpeg-bytes")
        }
        self.loader = PrivateStorageImageLoader(
            storage=PrivateStorageService(client=self.client, bucket=BUCKET)
        )

    def test_a_reference_loads_the_object_at_that_key(self):
        # Act
        data = self.loader(KEY)

        # Assert
        self.assertEqual(data, b"jpeg-bytes")
        self.client.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY)

    def test_an_image_is_read_from_storage_once_per_loader(self):
        # Act
        first = self.loader(KEY)
        second = self.loader(KEY)

        # Assert
        self.assertEqual(first, second)
        self.assertEqual(self.client.get_object.call_count, 1)

    def test_a_deleted_object_is_reported_as_unavailable(self):
        for code in ("NoSuchKey", "NotFound", "404"):
            # Arrange
            self.client.get_object.side_effect = _client_error(code)

            # Act / Assert
            with self.assertRaises(ImageUnavailableError):
                self.loader(KEY)

    def test_other_storage_failures_propagate(self):
        # Arrange
        self.client.get_object.side_effect = _client_error("SlowDown")

        # Act / Assert
        with self.assertRaises(ClientError):
            self.loader(KEY)

    def test_keys_outside_the_chat_files_prefix_are_never_read(self):
        # Act / Assert
        for ref in (
            "papers/1/figure.png",
            "uploads/research_ai/../papers/1/figure.png",
            "",
        ):
            with self.assertRaises(ImageUnavailableError):
                self.loader(ref)
        self.client.get_object.assert_not_called()

    def test_an_object_too_large_to_be_an_image_is_unavailable(self):
        # Arrange
        self.client.get_object.side_effect = lambda **kwargs: {
            "Body": io.BytesIO(b"x" * (image_loader._MAX_IMAGE_BYTES + 1))
        }

        # Act / Assert
        with self.assertRaises(ImageUnavailableError):
            self.loader(KEY)
