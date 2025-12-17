from unittest.mock import Mock

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from orcid.views.orcid_callback_view import OrcidCallbackView


class OrcidCallbackViewTests(TestCase):

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = OrcidCallbackView.as_view()
        self.mock_service = Mock()

    def test_error_param_redirects_cancelled(self):
        # Arrange
        self.mock_service.get_redirect_url.return_value = "https://researchhub.com?orcid_error=cancelled"
        request = self.factory.get("/api/orcid/callback/?error=access_denied")

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.mock_service.get_redirect_url.assert_called_with(error="cancelled")

    def test_missing_code_redirects_cancelled(self):
        # Arrange
        self.mock_service.get_redirect_url.return_value = "https://researchhub.com?orcid_error=cancelled"
        request = self.factory.get("/api/orcid/callback/?state=abc")

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.mock_service.get_redirect_url.assert_called_with(error="cancelled")

    def test_valid_code_calls_process_callback(self):
        # Arrange
        self.mock_service.process_callback.return_value = "https://researchhub.com?orcid_connected=true"
        request = self.factory.get("/api/orcid/callback/?code=abc&state=xyz")

        # Act
        response = self.view(request, orcid_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, "https://researchhub.com?orcid_connected=true")
        self.mock_service.process_callback.assert_called_once_with(code="abc", state="xyz")
