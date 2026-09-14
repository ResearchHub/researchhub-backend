from unittest.mock import MagicMock, patch

from django.test import TestCase

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from notification.tasks import email_notification_recipients
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


class EmailNotificationRecipientsTaskTests(TestCase):
    """`email_notification_recipients` emails everyone a notification reached."""

    @patch.object(EmailService, "send_email")
    @patch.object(Notification, "send_notification")
    def test_emails_every_recipient_of_the_given_notifications(
        self, _: MagicMock, mock_send_email: MagicMock
    ) -> None:
        """Each recipient gets the same message about the work they follow."""
        # Arrange
        author = create_random_default_user("author")
        followers = [
            create_random_default_user("follower1"),
            create_random_default_user("follower2"),
        ]
        paper = create_paper(uploaded_by=author)
        service = NotificationService()
        notification_ids = [
            service.send(
                Notification.PUBLICATIONS_ADDED,
                recipient=follower,
                action_user=author,
                item=paper,
                unified_document=paper.unified_document,
            ).id
            for follower in followers
        ]

        # Act
        email_notification_recipients(notification_ids, "Subject", "Message")

        # Assert
        emailed = [call.args[0] for call in mock_send_email.call_args_list]
        self.assertCountEqual(emailed, [[follower.email] for follower in followers])
