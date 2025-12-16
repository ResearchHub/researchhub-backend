from unittest.mock import patch

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.test import TestCase

from orcid.clients.orcid_client import OrcidClient
from orcid.services.orcid_service import OrcidService
from orcid.tests.helpers import create_orcid_app
from user.tests.helpers import create_random_default_user


class OrcidServiceTests(TestCase):

    def setUp(self):
        self.service = OrcidService()

    def test_build_auth_url(self):
        # Arrange
        create_orcid_app()

        # Act
        url = self.service.build_auth_url(123, "https://researchhub.com/settings")

        # Assert
        self.assertIn("test-id", url)
        self.assertIn("state=", url)
        self.assertIn("oauth/authorize", url)

    def test_build_auth_url_without_return_url(self):
        # Arrange
        create_orcid_app()

        # Act
        url = self.service.build_auth_url(123)

        # Assert
        self.assertIn("oauth/authorize", url)

    def test_connect_creates_account_token_and_updates_author(self):
        # Arrange
        user = create_random_default_user("test_user")
        create_orcid_app()
        token_data = {"orcid": "0000-0001-2345-6789", "access_token": "token", "refresh_token": "refresh", "expires_in": 3600}

        # Act
        self.service.connect_orcid_account(user, token_data)

        # Assert
        self.assertTrue(SocialAccount.objects.filter(user=user, provider=OrcidProvider.id).exists())
        self.assertEqual(SocialToken.objects.get(account__user=user).token, "token")
        user.author_profile.refresh_from_db()
        self.assertIn("0000-0001-2345-6789", user.author_profile.orcid_id)

    def test_decode_state_valid(self):
        # Arrange
        encoded = self.service._encode_signed_value({"user_id": 123})

        # Act
        result = self.service.decode_state(encoded)

        # Assert
        self.assertEqual(result["user_id"], 123)

    def test_decode_state_invalid(self):
        # Arrange
        invalid_state = "invalid"

        # Act
        result = self.service.decode_state(invalid_state)

        # Assert
        self.assertIsNone(result)

    def test_get_redirect_url_success(self):
        # Arrange
        return_url = "https://researchhub.com"

        # Act
        result = self.service.get_redirect_url(return_url=return_url)

        # Assert
        self.assertIn("orcid_connected=true", result)

    def test_get_redirect_url_error(self):
        # Arrange
        error = "failed"

        # Act
        result = self.service.get_redirect_url(error=error)

        # Assert
        self.assertIn("orcid_error=failed", result)

    def test_get_redirect_url_invalid_domain(self):
        # Arrange
        evil_url = "https://evil.com"

        # Act
        result = self.service.get_redirect_url(return_url=evil_url)

        # Assert
        self.assertNotIn("evil.com", result)


@patch.object(OrcidClient, "exchange_code_for_token")
class OrcidServiceCallbackTests(TestCase):

    def setUp(self):
        self.service = OrcidService()
        create_orcid_app()

    def test_process_callback_success(self, mock_exchange):
        # Arrange
        user = create_random_default_user("test_user")
        mock_exchange.return_value = {"orcid": "0000-0001-2345-6789", "access_token": "token"}
        state = self.service._encode_signed_value({"user_id": user.id, "return_url": "https://researchhub.com/profile"})

        # Act
        result = self.service.process_callback("auth_code", state)

        # Assert
        self.assertIn("orcid_connected=true", result)
        self.assertIn("researchhub.com/profile", result)
        self.assertTrue(SocialAccount.objects.filter(user=user).exists())

    def test_process_callback_invalid_state(self, mock_exchange):
        # Arrange
        invalid_state = "invalid"

        # Act
        result = self.service.process_callback("code", invalid_state)

        # Assert
        self.assertIn("orcid_error=invalid_state", result)

    def test_process_callback_user_not_found(self, mock_exchange):
        # Arrange
        state = self.service._encode_signed_value({"user_id": 99999})

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_error=invalid_state", result)

    def test_process_callback_already_linked(self, mock_exchange):
        # Arrange
        user1 = create_random_default_user("user1")
        user2 = create_random_default_user("user2")
        SocialAccount.objects.create(user=user1, provider=OrcidProvider.id, uid="0000-0001-2345-6789")
        mock_exchange.return_value = {"orcid": "0000-0001-2345-6789"}
        state = self.service._encode_signed_value({"user_id": user2.id})

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_error=already_linked", result)

    def test_process_callback_request_exception(self, mock_exchange):
        # Arrange
        user = create_random_default_user("user")
        state = self.service._encode_signed_value({"user_id": user.id})
        mock_exchange.side_effect = requests.RequestException()

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_error=service_error", result)

    def test_process_callback_missing_orcid_in_response(self, mock_exchange):
        # Arrange
        user = create_random_default_user("user")
        state = self.service._encode_signed_value({"user_id": user.id})
        mock_exchange.return_value = {"access_token": "token"}

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_error=service_error", result)
