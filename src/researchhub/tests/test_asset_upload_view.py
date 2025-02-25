from unittest.mock import Mock

from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from researchhub.asset_upload_view import AssetUploadView
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
        self.assertEqual(
            response.data,
            {
                "presigned_url": self.mock_storage_service.create_presigned_url.return_value.url,
                "object_key": self.mock_storage_service.create_presigned_url.return_value.object_key,
            },
        )
        self.mock_storage_service.create_presigned_url.assert_called_once_with(
            "paper",
            "test.pdf",
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
