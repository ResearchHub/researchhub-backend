from django.test import TestCase

from orcid.services.orcid_service import OrcidService
from orcid.tests.helpers import create_orcid_app


class OrcidServiceTests(TestCase):
    def setUp(self):
        self.service = OrcidService()

    def test_build_auth_url(self):
        create_orcid_app()
        url = self.service.build_auth_url(123, "https://researchhub.com/settings")

        self.assertIn("test-id", url)
        self.assertIn("state=", url)
        self.assertIn("oauth/authorize", url)

    def test_build_auth_url_without_return_url(self):
        create_orcid_app()
        url = self.service.build_auth_url(123)

        self.assertIn("state=", url)
        self.assertIn("oauth/authorize", url)
