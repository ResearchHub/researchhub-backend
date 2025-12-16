from django.test import TestCase

from orcid.services.orcid_service import OrcidService
from orcid.tests.helpers import create_orcid_app


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
        self.assertIn("state=", url)
        self.assertIn("oauth/authorize", url)
