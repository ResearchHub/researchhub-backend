from django.test import TestCase

from orcid.services import OrcidConnectService
from orcid.tests.helpers import create_orcid_app
from orcid.utils import is_valid_redirect_url


class OrcidConnectServiceTests(TestCase):

    def setUp(self):
        self.service = OrcidConnectService()

    def test_build_auth_url(self):
        # Arrange
        create_orcid_app()

        # Act
        url_with_return = self.service.build_auth_url(123, "https://researchhub.com/settings")
        url_without_return = self.service.build_auth_url(123)

        # Assert
        self.assertIn("test-id", url_with_return)
        self.assertIn("state=", url_with_return)
        self.assertIn("oauth/authorize", url_with_return)
        self.assertIn("state=", url_without_return)

    def test_is_valid_redirect_url(self):
        # Act
        valid = is_valid_redirect_url("https://researchhub.com/page")
        invalid = is_valid_redirect_url("https://evil.com")
        empty = is_valid_redirect_url(None)

        # Assert
        self.assertTrue(valid)
        self.assertFalse(invalid)
        self.assertFalse(empty)
