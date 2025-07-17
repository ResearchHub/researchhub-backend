from unittest.mock import patch

from django.test import TestCase

from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_comment.tasks import send_author_update_email_notifications
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user


class SendAuthorUpdateEmailNotificationsTaskTests(TestCase):
    def setUp(self):
        self.author = create_random_default_user("author")
        self.follower1 = create_random_default_user("follower1")
        self.follower2 = create_random_default_user("follower2")
        self.follower_no_email_recipient = create_random_default_user(
            "no_email_recipient"
        )

        # Create preregistration
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.preregistration = ResearchhubPost.objects.create(
            title="Test Preregistration for Email Notifications",
            document_type=PREREGISTRATION,
            created_by=self.author,
            unified_document=self.unified_doc,
        )

        # Create thread and comment
        self.thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=self.preregistration,
            created_by=self.author,
        )
        self.comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.author,
            comment_content_json={"text": "This is an author update for email testing"},
            comment_type=AUTHOR_UPDATE,
        )

        # Opt out follower2 from email notifications
        self.follower2.emailrecipient.set_opted_out(True)

        # Remove EmailRecipient for follower_no_email_recipient to test that case
        self.follower_no_email_recipient.emailrecipient.delete()

    @patch("researchhub_comment.tasks.send_email_message")
    def test_sends_emails_to_users_with_notification_preferences(self, mock_send_email):
        """
        Test that emails are sent only to users who want to receive notifications.
        """
        # Arrange
        follower_ids = [self.follower1.id, self.follower2.id]
        mock_send_email.return_value = {"success": [], "failure": [], "exclude": []}

        # Act
        send_author_update_email_notifications(self.comment.id, follower_ids)

        # Assert
        # Should only send to follower1 who has receives_notifications=True
        mock_send_email.assert_called_once()

        call_args = mock_send_email.call_args[0]
        self.assertEqual(call_args[0], [self.follower1.email])
        self.assertEqual(call_args[1], "general_email_message.txt")
        self.assertEqual(call_args[2], "Update on Preregistration You're Following")

        email_context = call_args[3]
        self.assertIn("action", email_context)
        self.assertIn("document_title", email_context)
        self.assertIn("author_name", email_context)
        self.assertEqual(email_context["document_title"], self.preregistration.title)
        self.assertEqual(email_context["author_name"], self.author.full_name())

    @patch("researchhub_comment.tasks.send_email_message")
    def test_skips_users_without_email_recipient_object(self, mock_send_email):
        """
        Test that users without EmailRecipient objects are skipped.
        """
        # Arrange
        follower_ids = [self.follower_no_email_recipient.id]
        mock_send_email.return_value = {"success": [], "failure": [], "exclude": []}

        # Act
        send_author_update_email_notifications(self.comment.id, follower_ids)

        # Assert
        mock_send_email.assert_not_called()

    @patch("researchhub_comment.tasks.logger")
    @patch("researchhub_comment.tasks.send_email_message")
    def test_handles_email_sending_failure_gracefully(
        self, mock_send_email, mock_logger
    ):
        """
        Test that the task handles email sending failures gracefully.
        """
        # Arrange
        follower_ids = [self.follower1.id]
        mock_send_email.side_effect = Exception("SMTP server error")

        # Act
        send_author_update_email_notifications(self.comment.id, follower_ids)

        # Assert
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        self.assertIn(str(self.follower1.id), error_message)

    @patch("researchhub_comment.tasks.send_email_message")
    def test_email_context_contains_correct_information(self, mock_send_email):
        """
        Test that the email context contains all the expected information.
        """
        # Arrange
        follower_ids = [self.follower1.id]
        mock_send_email.return_value = {"success": [], "failure": [], "exclude": []}

        # Act
        send_author_update_email_notifications(self.comment.id, follower_ids)

        # Assert
        mock_send_email.assert_called_once()

        call_args = mock_send_email.call_args
        email_context = call_args[0][3]

        # Check that context has base_email_context merged in
        self.assertIn("action", email_context)

        # Check action details
        action = email_context["action"]
        expected_message = (
            f"{self.author.first_name} {self.author.last_name} posted an update "
            "to a preregistration you're following"
        )
        self.assertEqual(action["message"], expected_message)

        expected_link = self.unified_doc.frontend_view_link()
        self.assertEqual(action["frontend_view_link"], expected_link)

        # Check other context fields
        self.assertEqual(email_context["document_title"], self.preregistration.title)
        self.assertEqual(email_context["author_name"], self.author.full_name())

    @patch("researchhub_comment.tasks.send_email_message")
    def test_processes_multiple_users_correctly(self, mock_send_email):
        """
        Test that the task processes multiple users correctly.
        """
        # Arrange
        # Create additional user with email preferences enabled
        follower3 = create_random_default_user("follower3")
        # follower3 will have EmailRecipient automatically created and enabled

        follower_ids = [self.follower1.id, self.follower2.id, follower3.id]
        mock_send_email.return_value = {"success": [], "failure": [], "exclude": []}

        # Act
        send_author_update_email_notifications(self.comment.id, follower_ids)

        # Assert
        # Should be called twice (for follower1 and follower3, but not follower2)
        self.assertEqual(mock_send_email.call_count, 2)

        # Get all call arguments
        call_args_list = mock_send_email.call_args_list
        sent_emails = [
            call[0][0][0] for call in call_args_list
        ]  # Extract email addresses

        self.assertIn(self.follower1.email, sent_emails)
        self.assertIn(follower3.email, sent_emails)
        self.assertNotIn(self.follower2.email, sent_emails)  # Should be excluded
