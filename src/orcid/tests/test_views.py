from unittest.mock import patch

import requests
from rest_framework import status
from rest_framework.test import APITestCase

from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_authenticated_user


class OrcidConnectViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("orcid_user")
        self.client.force_authenticate(user=self.user)
        self.app = create_orcid_app()

    def test_returns_auth_url(self):
        response = self.client.post("/api/orcid/connect/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("auth_url", response.data)

    def test_unauthenticated_user_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/orcid/connect/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_app_returns_error(self):
        self.app.delete()
        response = self.client.post("/api/orcid/connect/")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


class OrcidCallbackViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("callback_user")
        self.client.force_authenticate(user=self.user)
        self.app = create_orcid_app()
        self.valid_data = {"code": "abc", "state": str(self.user.id)}

    def test_no_code_returns_error(self):
        response = self.client.post("/api/orcid/callback/", {"state": str(self.user.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mismatched_user_returns_error(self):
        response = self.client.post("/api/orcid/callback/", {"code": "abc", "state": "999"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_user_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/orcid/callback/", {"code": "abc", "state": "123"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("orcid.views.connect_orcid_account")
    @patch("orcid.views.exchange_code_for_token")
    def test_success_returns_author_id(self, mock_exchange, mock_connect):
        mock_exchange.return_value = {"orcid": "0000-0001-2345-6789"}
        response = self.client.post("/api/orcid/callback/", self.valid_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["author_id"], self.user.author_profile.id)

    @patch("orcid.views.exchange_code_for_token")
    def test_value_error_returns_bad_request(self, mock_exchange):
        mock_exchange.side_effect = ValueError("ORCID already linked")
        response = self.client.post("/api/orcid/callback/", self.valid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ORCID already linked", response.data["error"])

    @patch("orcid.views.exchange_code_for_token")
    def test_request_error_returns_server_error(self, mock_exchange):
        mock_exchange.side_effect = requests.RequestException()
        response = self.client.post("/api/orcid/callback/", self.valid_data)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_missing_app_in_callback_returns_error(self):
        self.app.delete()
        response = self.client.post("/api/orcid/callback/", self.valid_data)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
