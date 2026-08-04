from urllib.parse import unquote

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings

from mailing_list.lib import send_email
from mailing_list.models import EmailOptOut
from mailing_list.services import EmailSubscriptionService

TEMPLATE_TXT = "general_email_message.txt"
TEMPLATE_HTML = "general_email_message.html"
BASE_CONTEXT = {"action": {"message": "hello"}, "subject": "Test"}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PRODUCTION=False,
)
class SendEmailTests(TestCase):
    """`send_email` suppresses opt-outs and attaches unsubscribe links."""

    def _send(self, recipients, **overrides):
        kwargs = {
            "recipients": recipients,
            "template": TEMPLATE_TXT,
            "subject": "Test",
            "email_context": {**BASE_CONTEXT},
            "html_template": TEMPLATE_HTML,
        }
        kwargs.update(overrides)
        return send_email(**kwargs)

    def test_sends_to_recipient_without_a_suppression_record(self):
        # Act
        result = self._send(["good@example.com"])

        # Assert
        self.assertEqual(result["success"], ["good@example.com"])
        self.assertEqual(len(mail.outbox), 1)

    def test_accepts_a_single_recipient_string(self):
        # Act
        result = self._send("good@example.com")

        # Assert
        self.assertEqual(result["success"], ["good@example.com"])
        self.assertEqual(len(mail.outbox), 1)

    def test_excludes_opted_out_recipient(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        result = self._send(["optout@example.com"])

        # Assert
        self.assertEqual(result["success"], [])
        self.assertIn("optout@example.com", result["exclude"])
        self.assertEqual(len(mail.outbox), 0)

    def test_excludes_opted_out_recipient_regardless_of_casing(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        result = self._send(["OptOut@Example.com"])

        # Assert
        self.assertEqual(result["success"], [])
        self.assertEqual(len(mail.outbox), 0)

    def test_sends_only_to_unsuppressed_recipients_in_a_mixed_list(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        result = self._send(["optout@example.com", "good@example.com"])

        # Assert
        self.assertEqual(result["success"], ["good@example.com"])
        self.assertIn("optout@example.com", result["exclude"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["good@example.com"])

    def test_sets_one_click_unsubscribe_headers(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        headers = mail.outbox[0].extra_headers
        self.assertEqual(headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn(
            f"{settings.BASE_FRONTEND_URL}/api/email/unsubscribe?",
            headers["List-Unsubscribe"],
        )

    def test_list_unsubscribe_url_carries_a_code_the_service_accepts(self):
        # Arrange
        service = EmailSubscriptionService()

        # Act
        self._send(["good@example.com"])

        # Assert: the header URL round-trips back to the same address. The code
        # is percent-encoded in the query string, as Django decodes it for the
        # view; do the same here.
        header = mail.outbox[0].extra_headers["List-Unsubscribe"]
        code = unquote(header.split("code=")[1].rstrip(">"))
        service.unsubscribe(code)
        self.assertEqual(
            EmailOptOut.filter_opted_out(["good@example.com"]), {"good@example.com"}
        )

    def test_each_recipient_gets_its_own_unsubscribe_url(self):
        # Act
        self._send(["a@example.com", "b@example.com"])

        # Assert
        first, second = (msg.extra_headers["List-Unsubscribe"] for msg in mail.outbox)
        self.assertNotEqual(first, second)

    def test_html_footer_carries_the_signed_unsubscribe_link(self):
        # Act
        self._send(["good@example.com"])

        # Assert: the footer link replaces the static, address-agnostic URL
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn(
            f"{settings.BASE_FRONTEND_URL}/email/unsubscribe/?code=", html_body
        )
        self.assertNotIn(f"{settings.BASE_FRONTEND_URL}/email/opt-out/", html_body)
