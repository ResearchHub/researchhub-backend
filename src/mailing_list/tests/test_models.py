from django.core import mail
from django.test import TestCase, override_settings

from mailing_list.lib import send_email
from mailing_list.models import EmailRecipient
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_default_user
)


class MailingListModelsTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user('mlm')

    def test_receives_notifications_is_false_if_bounced(self):
        user = create_random_default_user('Aaron')
        user.emailrecipient.bounced()
        self.assertFalse(user.emailrecipient.receives_notifications)

    def test_receives_notifications_is_false_if_opted_out(self):
        user = create_random_default_user('Baron')
        user.emailrecipient.set_opted_out(True)
        self.assertFalse(user.emailrecipient.receives_notifications)

    def test_receives_notifications_is_true_by_default(self):
        user = create_random_default_user('Caron')
        self.assertTrue(user.emailrecipient.receives_notifications)

    def test_receives_notifications_if_bounced_opted_out_and_subscribed(self):
        user = create_random_default_user('Daron')
        self.assertTrue(user.emailrecipient.receives_notifications)
        user.emailrecipient.set_opted_out(True)
        user.emailrecipient.bounced()
        self.assertFalse(user.emailrecipient.receives_notifications)


class GetSuppressedEmailsTests(TestCase):
    def test_returns_bounced_and_opted_out_emails(self):
        EmailRecipient.objects.create(email="bounced@example.com", do_not_email=True)
        EmailRecipient.objects.create(email="optout@example.com", is_opted_out=True)
        EmailRecipient.objects.create(email="good@example.com")

        result = EmailRecipient.get_suppressed_emails(
            ["bounced@example.com", "optout@example.com", "good@example.com"]
        )

        self.assertEqual(result, {"bounced@example.com", "optout@example.com"})

    def test_returns_empty_set_for_unknown_emails(self):
        result = EmailRecipient.get_suppressed_emails(["unknown@example.com"])

        self.assertEqual(result, set())


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PRODUCTION=False,
)
class SendEmailTests(TestCase):
    def test_send_email_excludes_suppressed_recipients(self):
        EmailRecipient.objects.create(email="bounced@example.com", do_not_email=True)

        result = send_email(
            recipients=["bounced@example.com"],
            template="general_email_message.txt",
            subject="Test",
            email_context={"action": {"message": "hello"}, "subject": "Test"},
            html_template="general_email_message.html",
        )

        self.assertEqual(result["success"], [])
        self.assertIn("bounced@example.com", result["exclude"])
        self.assertEqual(len(mail.outbox), 0)
