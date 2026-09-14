from unittest.mock import MagicMock, patch

from django.test import TestCase

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


@patch.object(Notification, "send_notification")
class NotificationServiceTests(TestCase):
    """`NotificationService` creates, pushes, and optionally emails a notification."""

    def setUp(self) -> None:
        """Create a recipient, an acting user, and something to notify about."""
        self.recipient = create_random_default_user("recipient")
        self.action_user = create_random_default_user("action_user")
        self.paper = create_paper(uploaded_by=self.action_user)
        self.service = NotificationService()

    def _send_once(self) -> Notification | None:
        """Send the deduplicated notification the tests send more than once."""
        return self.service.send_once(
            Notification.PUBLICATIONS_ADDED,
            recipient=self.recipient,
            action_user=self.action_user,
            item=self.paper,
        )

    def test_sends_a_notification_the_recipient_has_not_had_before(
        self, mock_send: MagicMock
    ) -> None:
        """The first send_once for an item creates and dispatches a notification."""
        # Act
        notification = self._send_once()

        # Assert
        mock_send.assert_called_once()
        self.assertEqual(notification.recipient, self.recipient)
        self.assertEqual(notification.object_id, self.paper.id)

    def test_skips_a_notification_the_recipient_already_has(
        self, mock_send: MagicMock
    ) -> None:
        """A repeated send_once for the same item notifies nobody a second time."""
        # Arrange
        self._send_once()
        mock_send.reset_mock()

        # Act
        notification = self._send_once()

        # Assert
        mock_send.assert_not_called()
        self.assertIsNone(notification)
        self.assertEqual(
            Notification.objects.filter(
                notification_type=Notification.PUBLICATIONS_ADDED,
                recipient=self.recipient,
            ).count(),
            1,
        )

    @patch.object(EmailService, "send_email")
    def test_emails_the_recipient_a_link_to_what_the_notification_is_about(
        self, mock_send_email: MagicMock, _: MagicMock
    ) -> None:
        """The email links to the page the notification itself points at."""
        # Act
        self.service.send(
            Notification.PUBLICATIONS_ADDED,
            recipient=self.recipient,
            action_user=self.action_user,
            item=self.paper,
            unified_document=self.paper.unified_document,
            email_subject="Subject",
            email_message="Message",
        )

        # Assert
        recipients, subject, context = mock_send_email.call_args.args
        self.assertEqual(recipients, [self.recipient.email])
        self.assertEqual(subject, "Subject")
        self.assertEqual(context["subject"], "Subject")
        self.assertEqual(context["action"]["message"], "Message")
        self.assertEqual(
            context["action"]["frontend_view_link"],
            self.paper.unified_document.frontend_view_link(),
        )

    @patch.object(EmailService, "send_email")
    def test_uses_a_separate_heading_inside_the_email(
        self, mock_send_email: MagicMock, _: MagicMock
    ) -> None:
        """A given heading banners the email without changing the inbox subject."""
        # Act
        self.service.send(
            Notification.PUBLICATIONS_ADDED,
            recipient=self.recipient,
            action_user=self.action_user,
            item=self.paper,
            unified_document=self.paper.unified_document,
            email_subject="Your ResearchHub Paper Was Added",
            email_heading="Paper Added",
            email_message="Message",
        )

        # Assert
        _, subject, context = mock_send_email.call_args.args
        self.assertEqual(subject, "Your ResearchHub Paper Was Added")
        self.assertEqual(context["subject"], "Paper Added")
