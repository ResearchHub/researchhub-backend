from unittest.mock import Mock

from allauth.socialaccount.models import SocialAccount, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.core import signing
from django.test import TestCase

from orcid.services import OrcidCallbackService
from orcid.tests.helpers import OrcidTestHelper
from user.tests.helpers import create_random_default_user


class OrcidCallbackServiceTests(TestCase):

    def setUp(self):
        self.mock_client = Mock()
        self.mock_email_service = Mock() 
        self.mock_email_service.fetch_verified_edu_emails.return_value = []
        self.service = OrcidCallbackService(
            client=self.mock_client,
            email_service=self.mock_email_service,
        )
        OrcidTestHelper.create_app()

    def test_process_callback_success(self):
        # Arrange
        user = create_random_default_user("test")
        self.mock_client.exchange_code_for_token.return_value = {
            "orcid": OrcidTestHelper.ORCID_ID, "access_token": "tk", "refresh_token": "rt", "expires_in": 3600
        }
        state = signing.dumps({"user_id": user.id, "return_url": "https://researchhub.com/p"})

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_connected=true", result)
        self.assertTrue(SocialAccount.objects.filter(user=user, provider=OrcidProvider.id).exists())
        self.assertEqual(SocialToken.objects.get(account__user=user).token, "tk")
        user.author_profile.refresh_from_db()
        self.assertIn(OrcidTestHelper.ORCID_ID, user.author_profile.orcid_id)

    def test_process_callback_invalid_state(self):
        # Act
        result = self.service.process_callback("code", "invalid")

        # Assert
        self.assertIn("orcid_error=error", result)

    def test_process_callback_user_not_found(self):
        # Arrange
        state = signing.dumps({"user_id": 999999})

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_error=error", result)

    def test_process_callback_already_linked(self):
        # Arrange
        user1 = create_random_default_user("u1")
        user2 = create_random_default_user("u2")
        SocialAccount.objects.create(user=user1, provider=OrcidProvider.id, uid=OrcidTestHelper.ORCID_ID)
        self.mock_client.exchange_code_for_token.return_value = {"orcid": OrcidTestHelper.ORCID_ID}
        state = signing.dumps({"user_id": user2.id})

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_error=already_linked", result)

    def test_process_callback_missing_orcid(self):
        # Arrange
        user = create_random_default_user("u")
        state = signing.dumps({"user_id": user.id})
        self.mock_client.exchange_code_for_token.return_value = {"access_token": "tk"}

        # Act
        result = self.service.process_callback("code", state)

        # Assert
        self.assertIn("orcid_error=error", result)

    def test_get_redirect_url(self):
        # Act
        success = self.service.get_redirect_url(return_url="https://researchhub.com?foo=bar")
        error = self.service.get_redirect_url(error="failed")
        invalid = self.service.get_redirect_url(return_url="https://evil.com")

        # Assert
        self.assertIn("orcid_connected=true", success)
        self.assertIn("foo=bar", success)
        self.assertIn("orcid_error=failed", error)
        self.assertNotIn("evil.com", invalid)

    def test_save_connection_stores_edu_emails(self):
        # Arrange
        user = create_random_default_user("edu")
        self.mock_email_service.fetch_verified_edu_emails.return_value = [
            "user@stanford.edu", "prof@oxford.ac.uk"
        ]
        token_data = {"orcid": OrcidTestHelper.ORCID_ID, "access_token": "tk"}

        # Act
        self.service._save_orcid_connection(user, token_data)

        # Assert
        account = SocialAccount.objects.get(user=user)
        self.assertEqual(
            account.extra_data["verified_edu_emails"],
            ["user@stanford.edu", "prof@oxford.ac.uk"]
        )
        self.mock_email_service.fetch_verified_edu_emails.assert_called_once_with(
            OrcidTestHelper.ORCID_ID, "tk"
        )