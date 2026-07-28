from django.core import mail
from django.test import TestCase, override_settings

from mailing_list.lib import send_email
from mailing_list.models import EmailRecipient

TEMPLATE_TXT = "general_email_message.txt"
TEMPLATE_HTML = "general_email_message.html"
BASE_CONTEXT = {"action": {"message": "hello"}, "subject": "Test"}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PRODUCTION=False,
)
class SendEmailTests(TestCase):
    """``send_email`` looks up suppressed addresses before delegating delivery."""

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

    def test_excludes_bounced_recipient(self):
        # Arrange
        EmailRecipient.objects.create(email="bounced@example.com", do_not_email=True)

        # Act
        result = self._send(["bounced@example.com"])

        # Assert
        self.assertEqual(result["success"], [])
        self.assertIn("bounced@example.com", result["exclude"])
        self.assertEqual(len(mail.outbox), 0)

    def test_excludes_opted_out_recipient(self):
        # Arrange
        EmailRecipient.objects.create(email="optout@example.com", is_opted_out=True)

        # Act
        result = self._send(["optout@example.com"])

        # Assert
        self.assertEqual(result["success"], [])
        self.assertIn("optout@example.com", result["exclude"])
        self.assertEqual(len(mail.outbox), 0)

    def test_sends_only_to_unsuppressed_recipients_in_a_mixed_list(self):
        # Arrange
        EmailRecipient.objects.create(email="optout@example.com", is_opted_out=True)

        # Act
        result = self._send(["optout@example.com", "good@example.com"])

        # Assert
        self.assertEqual(result["success"], ["good@example.com"])
        self.assertIn("optout@example.com", result["exclude"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["good@example.com"])
