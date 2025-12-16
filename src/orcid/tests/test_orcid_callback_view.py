from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from orcid.tests.helpers import create_orcid_app


@patch("orcid.views.orcid_callback_view.OrcidService")
class OrcidCallbackViewTests(APITestCase):

    def setUp(self):
        create_orcid_app()

    def test_error_param_redirects_cancelled(self, mock_service):
        # Arrange
        mock_service.return_value.get_redirect_url.return_value = "https://researchhub.com?orcid_error=cancelled"

        # Act
        response = self.client.get("/api/orcid/callback/?error=access_denied")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        mock_service.return_value.get_redirect_url.assert_called_with(error="cancelled")

    def test_missing_code_redirects_cancelled(self, mock_service):
        # Arrange
        mock_service.return_value.get_redirect_url.return_value = "https://researchhub.com?orcid_error=cancelled"

        # Act
        response = self.client.get("/api/orcid/callback/?state=abc")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        mock_service.return_value.get_redirect_url.assert_called_with(error="cancelled")

    def test_valid_code_calls_process_callback(self, mock_service):
        # Arrange
        mock_service.return_value.process_callback.return_value = "https://researchhub.com?orcid_connected=true"

        # Act
        response = self.client.get("/api/orcid/callback/?code=abc&state=xyz")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, "https://researchhub.com?orcid_connected=true")
        mock_service.return_value.process_callback.assert_called_once_with(code="abc", state="xyz")
