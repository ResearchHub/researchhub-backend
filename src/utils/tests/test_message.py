from django.core import mail
from django.test import TestCase, override_settings

from utils.message import deliver_email, is_valid_email

TEMPLATE_TXT = "general_email_message.txt"
TEMPLATE_HTML = "general_email_message.html"
BASE_CONTEXT = {"action": {"message": "hello"}, "subject": "Test"}


class IsValidEmailTests(TestCase):
    def test_allows_any_email_in_test_mode(self):
        self.assertTrue(is_valid_email("anyone@example.com"))

    @override_settings(TESTING=False, EMAIL_WHITELIST=["a@example.com"])
    def test_allows_whitelisted_email(self):
        self.assertTrue(is_valid_email("a@example.com"))

    @override_settings(TESTING=False, EMAIL_WHITELIST=["other@example.com"])
    def test_rejects_non_whitelisted_email(self):
        self.assertFalse(is_valid_email("blocked@example.com"))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PRODUCTION=False,
)
class DeliverEmailTests(TestCase):
    def _send(self, recipients="user@example.com", **overrides):
        kwargs = {
            "recipients": recipients,
            "template": TEMPLATE_TXT,
            "subject": "Test",
            "email_context": {**BASE_CONTEXT},
            "html_template": TEMPLATE_HTML,
        }
        kwargs.update(overrides)
        return deliver_email(**kwargs)

    def test_sends_to_valid_recipient(self):
        # Act
        result = self._send()

        # Assert
        self.assertEqual(result["success"], ["user@example.com"])
        self.assertEqual(len(mail.outbox), 1)

    def test_excludes_suppressed_emails(self):
        # Act
        result = self._send(
            recipients=["bounced@example.com"],
            suppressed_emails={"bounced@example.com"},
        )

        # Assert
        self.assertEqual(result["success"], [])
        self.assertIn("bounced@example.com", result["exclude"])
        self.assertEqual(len(mail.outbox), 0)

    def test_sets_precedence_bulk(self):
        # Act
        self._send()

        # Assert
        msg = mail.outbox[0]
        self.assertEqual(msg.extra_headers["Precedence"], "bulk")

    def test_list_unsubscribe_header_with_opt_out(self):
        # Act
        self._send(
            email_context={**BASE_CONTEXT, "opt_out": "https://example.com/unsub"}
        )

        # Assert
        headers = mail.outbox[0].extra_headers
        self.assertIn("List-Unsubscribe", headers)
        self.assertIn("List-Unsubscribe-Post", headers)

    def test_does_not_mutate_email_context(self):
        # Arrange
        context = {**BASE_CONTEXT, "opt_out": "https://example.com/unsub"}
        original_opt_out = context["opt_out"]

        # Act
        self._send(recipients=["a@example.com", "b@example.com"], email_context=context)

        # Assert
        self.assertEqual(context["opt_out"], original_opt_out)

    def test_reply_to_is_set(self):
        # Act
        self._send(reply_to="reply@example.com")

        # Assert
        self.assertEqual(mail.outbox[0].reply_to, ["reply@example.com"])
