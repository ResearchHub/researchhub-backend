from unittest.mock import patch

from allauth.socialaccount.models import SocialApp
from rest_framework import status
from rest_framework.test import APITestCase

from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_authenticated_user


@patch("orcid.views.orcid_connect_view.OrcidService")
class OrcidConnectViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("orcid_user")
        self.client.force_authenticate(user=self.user)
        create_orcid_app()

    def test_returns_auth_url(self, mock_service):
        mock_service.return_value.build_auth_url.return_value = "https://orcid.org/oauth?state=abc"

        response = self.client.post("/api/orcid/connect/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["auth_url"], "https://orcid.org/oauth?state=abc")
        mock_service.return_value.build_auth_url.assert_called_once_with(self.user.id, None)

        mock_service.reset_mock()
        response = self.client.post("/api/orcid/connect/", {"return_url": "https://researchhub.com/funds"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_service.return_value.build_auth_url.assert_called_once_with(self.user.id, "https://researchhub.com/funds")

    def test_unauthenticated_rejected(self, mock_service):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post("/api/orcid/connect/").status_code, status.HTTP_401_UNAUTHORIZED)

    def test_errors_return_500(self, mock_service):
        for error, expected_message in [
            (SocialApp.DoesNotExist(), "ORCID not configured"),
            (RuntimeError("error"), "Failed to initiate ORCID connection"),
        ]:
            mock_service.return_value.build_auth_url.side_effect = error
            response = self.client.post("/api/orcid/connect/")
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response.data["error"], expected_message)
