from unittest.mock import Mock

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from orcid.views import OrcidCallbackView


class OrcidCallbackViewTests(TestCase):

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = OrcidCallbackView.as_view()
        self.mock_service = Mock()

    def test_error_or_missing_code_redirects_cancelled(self):
        # Arrange
        self.mock_service.get_redirect_url.return_value = "https://rh.com?err=cancelled"

        # Act
        error_response = self.view(self.factory.get("/?error=denied"), orcid_callback_service=self.mock_service)
        missing_response = self.view(self.factory.get("/?state=abc"), orcid_callback_service=self.mock_service)

        # Assert
        self.assertEqual(error_response.status_code, 302)
        self.assertEqual(missing_response.status_code, 302)
        self.mock_service.get_redirect_url.assert_called_with(error="cancelled")

    def test_valid_code_calls_process_callback(self):
        # Arrange
        self.mock_service.process_callback.return_value = "https://rh.com?connected=true"
        request = self.factory.get("/?code=abc&state=xyz")

        # Act
        response = self.view(request, orcid_callback_service=self.mock_service)

        # Assert
        self.assertEqual(response.url, "https://rh.com?connected=true")
        self.mock_service.process_callback.assert_called_once_with(code="abc", state="xyz")

    def test_exception_in_service_redirects_with_error(self):
        # Arrange
        self.mock_service.process_callback.side_effect = Exception("Unexpected error")
        request = self.factory.get("/?code=abc&state=xyz")

        # Act
        response = self.view(request, orcid_callback_service=self.mock_service)

        # Assert
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{settings.BASE_FRONTEND_URL}?orcid_error=error")

