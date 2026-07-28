import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from mailing_list.models import EmailRecipient
from mailing_list.services.ses_event_service import SesEventService

EMAIL = "reader@example.com"


def bounce_obj(*emails: str, bounce_type: str = "Permanent") -> dict:
    """
    Build the `bounce` object SES publishes with a bounce event.
    """
    return {
        "bounceType": bounce_type,
        "bouncedRecipients": [{"emailAddress": email} for email in emails],
    }


def complaint_obj(*emails: str) -> dict:
    """
    Build the `complaint` object SES publishes with a complaint event.
    """
    return {"complainedRecipients": [{"emailAddress": email} for email in emails]}


class HandleBounceTests(TestCase):
    def setUp(self):
        self.service = SesEventService()

    def test_permanent_bounce_suppresses_the_recipient(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email=EMAIL)

        # Act
        self.service.handle_bounce(bounce_obj(EMAIL))

        # Assert
        recipient.refresh_from_db()
        self.assertTrue(recipient.do_not_email)
        self.assertIsNotNone(recipient.bounced_date)
        self.assertFalse(recipient.receives_notifications)

    def test_transient_bounce_leaves_the_recipient_alone(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email=EMAIL)

        # Act
        self.service.handle_bounce(bounce_obj(EMAIL, bounce_type="Transient"))

        # Assert
        recipient.refresh_from_db()
        self.assertFalse(recipient.do_not_email)
        self.assertIsNone(recipient.bounced_date)

    def test_creates_a_recipient_for_an_unknown_address(self):
        # Act
        self.service.handle_bounce(bounce_obj(EMAIL))

        # Assert
        self.assertTrue(EmailRecipient.objects.get(email=EMAIL).do_not_email)

    def test_matches_an_existing_recipient_regardless_of_case(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email=EMAIL)

        # Act
        self.service.handle_bounce(bounce_obj(EMAIL.upper()))

        # Assert
        self.assertEqual(EmailRecipient.objects.count(), 1)
        recipient.refresh_from_db()
        self.assertTrue(recipient.do_not_email)

    def test_suppresses_every_recipient_of_the_bounce(self):
        # Act
        self.service.handle_bounce(bounce_obj(EMAIL, "other@example.com"))

        # Assert
        self.assertEqual(EmailRecipient.objects.filter(do_not_email=True).count(), 2)


class HandleComplaintTests(TestCase):
    def setUp(self):
        self.service = SesEventService()

    def test_complaint_suppresses_the_recipient(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email=EMAIL)

        # Act
        self.service.handle_complaint(complaint_obj(EMAIL))

        # Assert
        recipient.refresh_from_db()
        self.assertTrue(recipient.do_not_email)
        self.assertFalse(recipient.receives_notifications)

    def test_complaint_does_not_record_a_bounce_date(self):
        # Arrange
        recipient = EmailRecipient.objects.create(email=EMAIL)

        # Act
        self.service.handle_complaint(complaint_obj(EMAIL))

        # Assert
        recipient.refresh_from_db()
        self.assertIsNone(recipient.bounced_date)


class SesWebhookTests(TestCase):
    """
    A bounce posted to the webhook has to reach the service.

    Note: Signature validation is disabled for these tests.
    """

    @patch(
        "django_ses.views.SESEventWebhookView.verify_event_message",
        return_value=True,
    )
    def test_bounce_notification_suppresses_the_recipient(self, _verify):
        # Arrange
        recipient = EmailRecipient.objects.create(email=EMAIL)
        notification = {
            "Type": "Notification",
            "Message": json.dumps(
                {
                    "notificationType": "Bounce",
                    "mail": {"messageId": "ses-message-id"},
                    "bounce": bounce_obj(EMAIL),
                }
            ),
        }

        # Act
        response = self.client.post(
            reverse("ses_event_webhook"),
            data=json.dumps(notification),
            content_type="application/json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        recipient.refresh_from_db()
        self.assertTrue(recipient.do_not_email)
