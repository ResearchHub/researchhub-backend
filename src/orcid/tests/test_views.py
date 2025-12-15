from unittest.mock import patch

import requests
from rest_framework import status
from rest_framework.test import APITestCase

from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_authenticated_user
from utils.signer import encode_signed_value


class OrcidConnectViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("orcid_user")
        self.client.force_authenticate(user=self.user)
        self.app = create_orcid_app()

    def test_returns_auth_url(self):
        response = self.client.post("/api/orcid/connect/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("state=", response.data["auth_url"])

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post("/api/orcid/connect/").status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_app_returns_500(self):
        self.app.delete()
        self.assertEqual(self.client.post("/api/orcid/connect/").status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @patch("orcid.views.build_auth_url", side_effect=RuntimeError("error"))
    def test_unexpected_error_returns_500(self, _):
        response = self.client.post("/api/orcid/connect/")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["error"], "Failed to initiate ORCID connection")


class OrcidCallbackViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("callback_user")
        self.app = create_orcid_app()
        self.state = encode_signed_value({"user_id": self.user.id})

    def _get(self, query):
        return self.client.get(f"/api/orcid/callback/?{query}")

    def _assert_redirect(self, response, expected_param):
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn(expected_param, response.url)

    def test_error_redirects(self):
        for query in [f"state={self.state}", "error=access_denied"]:
            with self.subTest(query=query):
                self._assert_redirect(self._get(query), "orcid_error=cancelled")

    def test_invalid_state_redirects(self):
        cases = ["code=abc&state=invalid", f"code=abc&state={encode_signed_value({'user_id': 99999})}"]
        for query in cases:
            with self.subTest(query=query):
                self._assert_redirect(self._get(query), "orcid_error=invalid_state")

    @patch("orcid.views.connect_orcid_account")
    @patch("orcid.views.exchange_code_for_token", return_value={"orcid": "0000-0001-2345-6789"})
    def test_success_redirects(self, *_):
        self._assert_redirect(self._get(f"code=abc&state={self.state}"), "orcid_connected=true")

    @patch("orcid.views.connect_orcid_account")
    @patch("orcid.views.exchange_code_for_token", return_value={"orcid": "0000-0001-2345-6789"})
    def test_success_uses_return_url(self, *_):
        state = encode_signed_value({"user_id": self.user.id, "return_url": "https://researchhub.com/funds"})
        response = self._get(f"code=abc&state={state}")
        self._assert_redirect(response, "https://researchhub.com/funds")
        self.assertIn("orcid_connected=true", response.url)

    def test_exception_redirects(self):
        cases = [
            (ValueError("linked"), "orcid_error=already_linked"),
            (requests.RequestException(), "orcid_error=service_error"),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                with patch("orcid.views.exchange_code_for_token", side_effect=exc):
                    self._assert_redirect(self._get(f"code=abc&state={self.state}"), expected)

    def test_missing_app_redirects(self):
        self.app.delete()
        self._assert_redirect(self._get(f"code=abc&state={self.state}"), "orcid_error=service_error")
