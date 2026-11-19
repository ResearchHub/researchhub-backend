from unittest.mock import Mock

from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from researchhub.services.storage_service import PresignedPost
from researchhub.views.asset_upload_view import AssetUploadView
from user.related_models.user_model import User


class AssetUploadViewTest(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AssetUploadView.as_view()
        self.mock_storage_service = Mock()
        self.user = User.objects.create(username="user1")

    def test_post(self):
        # Arrange
        request = self.factory.post(
            "/asset/upload/",
            {
                "content_type": "application/pdf",
                "entity": "paper",
                "filename": "test.pdf",
            },
        )

        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 200)
        presigned = self.mock_storage_service.create_presigned_url.return_value
        self.assertEqual(
            response.data,
            {
                "presigned_url": presigned.url,
                "object_key": presigned.object_key,
                "object_url": presigned.object_url,
            },
        )
        self.mock_storage_service.create_presigned_url.assert_called_once_with(
            "paper",
            "test.pdf",
            request.user.id,
            "application/pdf",
        )

    def test_post_with_post_upload_method_returns_form_upload(self):
        # Arrange
        self.mock_storage_service.create_presigned_post.return_value = PresignedPost(
            object_key="uploads/posts/users/1/uuid/cover.png",
            object_url="https://storage.test/uploads/posts/users/1/uuid/cover.png",
            url="https://bucket.s3.amazonaws.com/",
            fields={"key": "uploads/posts/users/1/uuid/cover.png", "policy": "abc"},
            max_bytes=10485760,
        )
        request = self.factory.post(
            "/asset/upload/",
            {
                "content_type": "image/png",
                "entity": "post",
                "filename": "cover.png",
                "upload_method": "post",
            },
        )
        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "upload": {
                    "url": "https://bucket.s3.amazonaws.com/",
                    "fields": {
                        "key": "uploads/posts/users/1/uuid/cover.png",
                        "policy": "abc",
                    },
                },
                "max_bytes": 10485760,
                "object_key": "uploads/posts/users/1/uuid/cover.png",
                "object_url": (
                    "https://storage.test/uploads/posts/users/1/uuid/cover.png"
                ),
            },
        )
        self.mock_storage_service.create_presigned_post.assert_called_once_with(
            "post", "cover.png", self.user.id, "image/png"
        )
        self.mock_storage_service.create_presigned_url.assert_not_called()

    def test_post_with_put_upload_method_returns_presigned_url(self):
        # Arrange
        request = self.factory.post(
            "/asset/upload/",
            {
                "content_type": "image/png",
                "entity": "post",
                "filename": "cover.png",
                "upload_method": "put",
            },
        )
        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("presigned_url", response.data)
        self.mock_storage_service.create_presigned_post.assert_not_called()

    def test_post_rejects_unknown_upload_method(self):
        # Arrange
        request = self.factory.post(
            "/asset/upload/",
            {
                "content_type": "image/png",
                "entity": "post",
                "filename": "cover.png",
                "upload_method": "patch",
            },
        )
        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("upload_method", response.data)

    def test_post_filename_with_special_characters(self):
        # Arrange
        request = self.factory.post(
            "/asset/upload/",
            {
                "content_type": "application/pdf",
                "entity": "paper",
                "filename": "test)(*&^%$#@!)123.pdf",
            },
        )

        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 200)
        presigned = self.mock_storage_service.create_presigned_url.return_value
        self.assertEqual(
            response.data,
            {
                "presigned_url": presigned.url,
                "object_key": presigned.object_key,
                "object_url": presigned.object_url,
            },
        )
        self.mock_storage_service.create_presigned_url.assert_called_once_with(
            "paper",
            "test123.pdf",
            request.user.id,
            "application/pdf",
        )

    def test_post_fails_unauthenticated(self):
        # Arrange
        request = self.factory.post("/assets/upload/")

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 401)
        self.mock_storage_service.create_presigned_url.assert_not_called()

    def test_post_fails_with_validation_error(self):
        # Arrange
        request = self.factory.post(
            "/asset/upload/",
            {
                # content type is missing!
                "entity": "paper",
                "filename": "test.pdf",
            },
        )

        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"content_type": ["This field is required."]})
        self.mock_storage_service.create_presigned_url.assert_not_called()

    def test_post_with_unsupported_entity(self):
        # Arrange
        request = self.factory.post(
            "/asset/upload/",
            {
                "content_type": "application/pdf",
                "entity": "UNSUPPORTED",
                "filename": "test.pdf",
            },
        )

        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"entity": ['"UNSUPPORTED" is not a valid choice.']},
        )
        self.mock_storage_service.create_presigned_url.assert_not_called()
