from django.test import TestCase, override_settings

from orcid.services import OrcidConnectService
from orcid.tests.helpers import OrcidTestHelper
from orcid.utils import is_valid_redirect_url


class OrcidConnectServiceTests(TestCase):
    def setUp(self):
        self.service = OrcidConnectService()

    def test_build_auth_url(self):
        # Arrange
        OrcidTestHelper.create_app()

        # Act
        url_with_return = self.service.build_auth_url(
            123, "https://researchhub.com/settings"
        )
        url_without_return = self.service.build_auth_url(123)

        # Assert
        self.assertIn("test-id", url_with_return)
        self.assertIn("state=", url_with_return)
        self.assertIn("oauth/authorize", url_with_return)
        self.assertIn("state=", url_without_return)

    def test_is_valid_redirect_url(self):
        # Arrange
        preview_origin = (
            "https://0123456789abcdef0123456789abcdef-87d3f8ab798deaec"
            ".preview.codepress.dev/settings"
        )

        # Act
        with override_settings(
            CORS_ALLOWED_ORIGIN_REGEXES=[
                r"^https://[0-9a-f]{32}-87d3f8ab798deaec\.preview\.codepress\.dev$"
            ]
        ):
            valid = is_valid_redirect_url("https://researchhub.com/page")
            preview_valid = is_valid_redirect_url(preview_origin)
            invalid = is_valid_redirect_url("https://evil.com")
            empty = is_valid_redirect_url(None)

        # Assert
        self.assertTrue(valid)
        self.assertTrue(preview_valid)
        self.assertFalse(invalid)
        self.assertFalse(empty)
