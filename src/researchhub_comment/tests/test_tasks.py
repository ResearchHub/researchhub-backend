from unittest.mock import Mock, patch

from celery.exceptions import Retry
from django.test import TestCase

from research_ai.services.message_screening.jev_client import DecisionError
from researchhub_comment.services.comment_spam_screening_service import (
    CommentSpamScreeningService,
)
from researchhub_comment.tasks import celery_screen_comment_for_spam
from researchhub_comment.tests.helpers import create_rh_comment


class ScreenCommentForSpamTaskTests(TestCase):
    def setUp(self) -> None:
        """Create a comment to screen."""
        self.comment = create_rh_comment()

    @patch.object(CommentSpamScreeningService, "screen")
    def test_screens_the_comment(self, mock_screen: Mock) -> None:
        """The task screens the comment it was queued for."""
        # Act
        celery_screen_comment_for_spam(self.comment.id)

        # Assert
        mock_screen.assert_called_once_with(self.comment)

    @patch.object(celery_screen_comment_for_spam, "retry", side_effect=Retry())
    @patch.object(CommentSpamScreeningService, "screen")
    def test_retries_when_jev_fails(self, mock_screen: Mock, mock_retry: Mock) -> None:
        """A Jev failure retries the task instead of dropping the screening."""
        # Arrange
        error = DecisionError("Jev timed out")
        mock_screen.side_effect = error

        # Act
        with self.assertRaises(Retry):
            celery_screen_comment_for_spam(self.comment.id)

        # Assert
        mock_retry.assert_called_once_with(exc=error)
