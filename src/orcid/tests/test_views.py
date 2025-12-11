from unittest.mock import PropertyMock, patch

import requests
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from rest_framework import status
from rest_framework.test import APITestCase

from orcid.tests.helpers import create_orcid_app
from user.related_models.author_model import Author
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

    @patch("orcid.views.connect_orcid_account")
    @patch("orcid.views.exchange_code_for_token")
    def test_success_without_author_returns_none(self, mock_exchange, mock_connect):
        mock_exchange.return_value = {"orcid": "0000-0001-2345-6789"}
        with patch.object(
            type(self.user), "author_profile", new_callable=PropertyMock
        ) as mock_profile:
            mock_profile.side_effect = AttributeError()
            response = self.client.post("/api/orcid/callback/", self.valid_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIsNone(response.data["author_id"])

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


class OrcidFetchViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("fetch_user")
        self.client.force_authenticate(user=self.user)
        SocialAccount.objects.create(
            user=self.user, provider=OrcidProvider.id, uid="0000-0001-2345-6789"
        )

    def test_unauthenticated_user_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/orcid/fetch/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_orcid_returns_error(self):
        SocialAccount.objects.filter(user=self.user).delete()
        response = self.client.post("/api/orcid/fetch/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not connected", response.data["error"])

    def test_no_author_profile_returns_error(self):
        Author.objects.filter(user=self.user).delete()
        self.user.refresh_from_db()
        response = self.client.post("/api/orcid/fetch/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Author profile not found", response.data["error"])

    @patch("orcid.views.fetch_orcid_works_task.delay")
    def test_success_queues_task(self, mock_delay):
        response = self.client.post("/api/orcid/fetch/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        mock_delay.assert_called_once_with(self.user.author_profile.id)

