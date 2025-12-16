from unittest.mock import patch

from allauth.socialaccount.models import SocialApp
from requests.exceptions import RequestException
from rest_framework import status
from rest_framework.test import APITestCase

from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_authenticated_user


@patch("orcid.views.orcid_callback_view.OrcidService")
class OrcidCallbackViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("callback_user")
        create_orcid_app()

    def _get(self, query: str):
        return self.client.get(f"/api/orcid/callback/?{query}")

    def test_error_or_missing_code_redirects_cancelled(self, mock_service):
        mock_service.return_value.get_redirect_url.return_value = "https://researchhub.com?orcid_error=cancelled"

        for query in ["error=access_denied", "state=abc"]:
            response = self._get(query)
            self.assertEqual(response.status_code, status.HTTP_302_FOUND)

    def test_invalid_state_or_user_redirects(self, mock_service):
        mock_service.return_value.get_redirect_url.return_value = "https://researchhub.com?orcid_error=invalid_state"

        mock_service.return_value.decode_state.return_value = None
        self.assertEqual(self._get("code=abc&state=bad").status_code, status.HTTP_302_FOUND)

        mock_service.return_value.decode_state.return_value = {"user_id": 99999}
        self.assertEqual(self._get("code=abc&state=valid").status_code, status.HTTP_302_FOUND)

    def test_success_redirects_with_return_url(self, mock_service):
        mock_service.return_value.decode_state.return_value = {"user_id": self.user.id, "return_url": "https://researchhub.com/funds"}
        mock_service.return_value.exchange_code_for_token.return_value = {"orcid": "0000-0001-2345-6789"}
        mock_service.return_value.get_redirect_url.return_value = "https://researchhub.com/funds?orcid_connected=true"

        response = self._get("code=abc&state=valid")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        mock_service.return_value.connect_orcid_account.assert_called_once()
        mock_service.return_value.get_redirect_url.assert_called_with(return_url="https://researchhub.com/funds")

    def test_already_linked_redirects(self, mock_service):
        mock_service.return_value.decode_state.return_value = {"user_id": self.user.id}
        mock_service.return_value.exchange_code_for_token.return_value = {"orcid": "0000-0001-2345-6789"}
        mock_service.return_value.connect_orcid_account.side_effect = ValueError()
        mock_service.return_value.get_redirect_url.return_value = "https://researchhub.com?orcid_error=already_linked"

        self.assertEqual(self._get("code=abc&state=valid").status_code, status.HTTP_302_FOUND)

    def test_service_errors_redirect(self, mock_service):
        mock_service.return_value.decode_state.return_value = {"user_id": self.user.id}
        mock_service.return_value.get_redirect_url.return_value = "https://researchhub.com?orcid_error=service_error"

        for error in [RequestException(), SocialApp.DoesNotExist()]:
            mock_service.return_value.exchange_code_for_token.side_effect = error
            self.assertEqual(self._get("code=abc&state=valid").status_code, status.HTTP_302_FOUND)
