from unittest.mock import MagicMock, patch

from django.http import HttpRequest
from django.test import SimpleTestCase, TestCase, override_settings

from user.custom_allauth import CustomAccountAdapter, CustomResetPasswordForm

SETTINGS = {
    "BASE_FRONTEND_URL": "https://www.researchhub.com",
    "ASSETS_BASE_URL": "https://assets.researchhub.com",
}


class DummyEmailAddress:
    def __init__(self, email):
        self.email = email


class DummyEmailConfirmation:
    def __init__(self, key, email="test@example.com"):
        self.key = key
        self.email_address = DummyEmailAddress(email)


class CustomAccountAdapterTests(SimpleTestCase):
    def setUp(self):
        self.request = HttpRequest()
        self.adapter = CustomAccountAdapter()

    @override_settings(**SETTINGS)
    def test_get_email_confirmation_url(self):
        # Act
        url = self.adapter.get_email_confirmation_url(
            self.request, DummyEmailConfirmation("abc123")
        )

        # Assert
        self.assertEqual(url, "https://www.researchhub.com/verify/abc123")

    @override_settings(**SETTINGS)
    @patch("user.custom_allauth.send_email_message")
    def test_send_confirmation_mail(self, mock_send):
        # Act
        confirm = DummyEmailConfirmation("key1", email="user@example.com")
        self.adapter.send_confirmation_mail(self.request, confirm, signup=True)

        # Assert
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertEqual(args[0], "user@example.com")
        self.assertEqual(args[2], "Confirm Your Email Address")
        self.assertTrue(kwargs["is_transactional"])
        self.assertEqual(kwargs["html_template"], "general_branded_email.html")
        self.assertEqual(args[3]["cta_url"], "https://www.researchhub.com/verify/key1")


class CustomResetPasswordFormTests(TestCase):
    @override_settings(**SETTINGS)
    @patch("user.custom_allauth.send_email_message")
    def test_save_sends_reset_email_and_returns_email(self, mock_send):
        # Arrange
        form = CustomResetPasswordForm.__new__(CustomResetPasswordForm)
        form.cleaned_data = {"email": "user@example.com"}
        form.users = [MagicMock(pk=1)]

        token_generator = MagicMock()
        token_generator.make_token.return_value = "tok"

        # Act
        result = form.save(request=HttpRequest(), token_generator=token_generator)

        # Assert
        self.assertEqual(result, "user@example.com")
        args, kwargs = mock_send.call_args
        self.assertEqual(args[0], "user@example.com")
        self.assertEqual(args[2], "Reset Your Password")
        self.assertTrue(kwargs["is_transactional"])
