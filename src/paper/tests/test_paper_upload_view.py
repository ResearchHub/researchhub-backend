from types import SimpleNamespace
from unittest.mock import Mock

from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from paper.views.paper_upload_views import PaperUploadView
from user.tests.helpers import create_random_default_user


class PaperUploadViewTest(APITestCase):

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PaperUploadView.as_view()
        self.user = create_random_default_user("user1")

        self.mock_storage_service = Mock()
        self.mock_storage_service.create_presigned_url.return_value = SimpleNamespace(
            url="https://presigned.url",
            object_key="paper/test.pdf",
            object_url="https://storage/paper/test.pdf",
        )

    def test_post(self):
        # Arrange
        request = self.factory.post(
            "/paper/upload/",
            {
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
                "presigned_url": "https://presigned.url",
                "object_key": "paper/test.pdf",
                "object_url": "https://storage/paper/test.pdf",
            },
        )
        self.mock_storage_service.create_presigned_url.assert_called_once_with(
            "paper",
            "test.pdf",
            request.user.id,
            "application/pdf",
        )

    def test_post_fails_with_validation_error(self):
        # Arrange
        request = self.factory.post("/paper/upload/", {})

        force_authenticate(request, self.user)

        # Act
        response = self.view(request, storage_service=self.mock_storage_service)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"filename": ["This field is required."]})
        self.mock_storage_service.create_presigned_url.assert_not_called()
