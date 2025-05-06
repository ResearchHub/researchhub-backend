from django.http import HttpRequest
from django.test import SimpleTestCase, override_settings

from user.custom_allauth import CustomAccountAdapter


class DummyEmailConfirmation:
    def __init__(self, key):
        self.key = key


class CustomAccountAdapterTests(SimpleTestCase):
    def setUp(self):
        self.request = HttpRequest()
        self.adapter = CustomAccountAdapter()

    @override_settings(
        PRODUCTION=True,
        BASE_FRONTEND_URL="https://www.researchhub.com",
    )
    def test_get_email_confirmation_url_production(self):
        # Arrange
        confirm = DummyEmailConfirmation("prod")

        # Act
        url = self.adapter.get_email_confirmation_url(self.request, confirm)

        # Assert
        self.assertEqual(url, "https://new.researchhub.com/verify/prod")

    @override_settings(
        STAGING=True,
        BASE_FRONTEND_URL="https://www.researchhub.com",
    )
    def test_get_email_confirmation_url_staging(self):
        # Arrange
        confirm = DummyEmailConfirmation("staging")

        # Act
        url = self.adapter.get_email_confirmation_url(self.request, confirm)

        # Assert
        self.assertEqual(url, "https://v2.staging.researchhub.com/verify/staging")

    @override_settings(
        BASE_FRONTEND_URL="https://default.researchhub.com",
    )
    def test_get_email_confirmation_url_default(self):
        # Arrange
        confirm = DummyEmailConfirmation("default")

        # Act
        url = self.adapter.get_email_confirmation_url(self.request, confirm)

        # Assert
        self.assertEqual(url, "https://default.researchhub.com/verify/default")
