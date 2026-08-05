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

    @patch("researchhub_comment.tasks.send_email")
    def test_sends_email_to_each_follower(self, mock_send_email):
        """
        Test that an email is sent to every follower.

        Suppressed and opted-out addresses are filtered by ``send_email``
        itself, so this task does not gate on notification preferences.
        """
        # Arrange
        follower_ids = [self.follower1.id, self.follower2.id]
        mock_send_email.return_value = {"success": [], "failure": [], "exclude": []}

        # Act
        send_author_update_email_notifications(self.comment.id, follower_ids)

        # Assert
        self.assertEqual(mock_send_email.call_count, 2)

        recipients = [call[0][0] for call in mock_send_email.call_args_list]
        self.assertIn([self.follower1.email], recipients)
        self.assertIn([self.follower2.email], recipients)

        call_args = mock_send_email.call_args_list[0][0]
        self.assertEqual(call_args[1], "general_email_message.txt")
        self.assertEqual(call_args[2], "Update on Preregistration You're Following")

        email_context = call_args[3]
        self.assertIn("action", email_context)
        self.assertIn("document_title", email_context)
        self.assertIn("author_name", email_context)
        self.assertEqual(email_context["document_title"], self.preregistration.title)
        self.assertEqual(email_context["author_name"], self.author.full_name())

    @patch("researchhub_comment.tasks.logger")
    @patch("researchhub_comment.tasks.send_email")
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

    @patch("researchhub_comment.tasks.send_email")
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

    @patch("researchhub_comment.tasks.send_email")
    def test_processes_multiple_users_correctly(self, mock_send_email):
        """
        Test that the task processes multiple users correctly.
        """
        # Arrange
        follower3 = create_random_default_user("follower3")

        follower_ids = [self.follower1.id, self.follower2.id, follower3.id]
        mock_send_email.return_value = {"success": [], "failure": [], "exclude": []}

        # Act
        send_author_update_email_notifications(self.comment.id, follower_ids)

        # Assert
        self.assertEqual(mock_send_email.call_count, 3)

        # Get all call arguments
        call_args_list = mock_send_email.call_args_list
        sent_emails = [
            call[0][0][0] for call in call_args_list
        ]  # Extract email addresses

        self.assertIn(self.follower1.email, sent_emails)
        self.assertIn(self.follower2.email, sent_emails)
        self.assertIn(follower3.email, sent_emails)
