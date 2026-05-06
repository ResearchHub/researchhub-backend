from django.test import TestCase
from django_ses.signals import bounce_received, open_received

from research_ai.models import GeneratedEmail
from user.tests.helpers import create_random_authenticated_user


class SesEventSignalTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("ses_events")
        self.email = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_email="expert@researchhub.com",
            email_subject="subject1",
            email_body="body1",
            ses_message_id="messageId1",
            status=GeneratedEmail.Status.SENT,
        )

    def _send_open(self, message_id="messageId1", timestamp="2026-05-01T12:00:00.000Z"):
        open_received.send(
            sender=self.__class__,
            mail_obj={"messageId": message_id},
            open_obj={"timestamp": timestamp},
            raw_message=b"",
        )

    def _send_bounce(
        self, message_id="messageId1", timestamp="2026-05-01T12:00:00.000Z"
    ):
        bounce_received.send(
            sender=self.__class__,
            mail_obj={"messageId": message_id},
            bounce_obj={
                "timestamp": timestamp,
                "bouncedRecipients": [{"emailAddress": "expert@researchhub.com"}],
            },
            raw_message=b"",
        )

    def test_first_open_sets_opened_at_and_increments_count(self):
        # Act
        self._send_open()

        # Assert
        self.email.refresh_from_db()
        self.assertEqual(self.email.open_count, 1)
        self.assertIsNotNone(self.email.opened_at)

    def test_subsequent_opens_increment_count_but_keep_first_opened_at(self):
        # Arrange
        self._send_open(timestamp="2026-05-01T12:00:00.000Z")
        self.email.refresh_from_db()
        first_opened_at = self.email.opened_at

        # Act
        self._send_open(timestamp="2026-05-02T15:00:00.000Z")

        # Assert
        self.email.refresh_from_db()
        self.assertEqual(self.email.open_count, 2)
        self.assertEqual(self.email.opened_at, first_opened_at)

    def test_bounce_sets_status_and_timestamp(self):
        # Act
        self._send_bounce()

        # Assert
        self.email.refresh_from_db()
        self.assertEqual(self.email.status, GeneratedEmail.Status.BOUNCED)
        self.assertIsNotNone(self.email.bounced_at)
