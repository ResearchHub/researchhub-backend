from unittest import TestCase
from unittest.mock import patch


class TestSendEmailMessageListMutation(TestCase):
    """Verify that invalid-recipient filtering no longer mutates the list
    while iterating (which used to skip recipients)."""

    @patch("utils.message.send_mail")
    @patch("utils.message.render_to_string", return_value="rendered")
    @patch("utils.message.settings")
    def test_excludes_invalid_without_skipping_valid(
        self, mock_settings, mock_render, mock_send
    ):
        mock_settings.TESTING = False
        mock_settings.PRODUCTION = False
        mock_settings.EMAIL_WHITELIST = ["a@ok.com", "c@ok.com"]
        mock_settings.DEFAULT_FROM_EMAIL = "noreply@test.com"

        from utils.message import send_email_message

        result = send_email_message(
            recipients=["a@ok.com", "b@bad.com", "c@ok.com"],
            template="t.txt",
            subject="test",
            email_context={},
            html_template="t.html",
        )

        self.assertEqual(result["exclude"], ["b@bad.com"])
        self.assertIn("a@ok.com", result["success"])
        self.assertIn("c@ok.com", result["success"])
        self.assertEqual(len(result["success"]), 2)

    @patch("utils.message.send_mail")
    @patch("utils.message.render_to_string", return_value="rendered")
    @patch("utils.message.settings")
    def test_consecutive_invalid_recipients_all_excluded(
        self, mock_settings, mock_render, mock_send
    ):
        mock_settings.TESTING = False
        mock_settings.PRODUCTION = False
        mock_settings.EMAIL_WHITELIST = ["d@ok.com"]
        mock_settings.DEFAULT_FROM_EMAIL = "noreply@test.com"

        from utils.message import send_email_message

        result = send_email_message(
            recipients=["a@bad.com", "b@bad.com", "c@bad.com", "d@ok.com"],
            template="t.txt",
            subject="test",
            email_context={},
            html_template="t.html",
        )

        self.assertEqual(sorted(result["exclude"]), ["a@bad.com", "b@bad.com", "c@bad.com"])
        self.assertEqual(result["success"], ["d@ok.com"])
