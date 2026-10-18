from datetime import timedelta
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import User
from user.services.complete_profile_email_service import CompleteProfileEmailService
from user.signals.complete_profile_email_signals import (
    queue_complete_profile_email_on_note_publish,
)
from user.tests.helpers import create_random_default_user


class CompleteProfileEmailServiceTests(TestCase):
    def setUp(self):
        self.email_service = Mock()
        self.service = CompleteProfileEmailService(email_service=self.email_service)
        self.user = create_random_default_user("complete_profile")

    def _set_date_joined(self, user: User, days_ago: float) -> None:
        """Backdate the user's account creation by the given number of days."""
        User.objects.filter(id=user.id).update(
            date_joined=timezone.now() - timedelta(days=days_ago)
        )

    def test_sends_profile_link_when_profile_is_incomplete(self):
        """The email links an incomplete profile to their author profile."""
        # Act
        self.service.send_if_eligible(self.user.id)

        # Assert
        author_id = self.user.author_profile.id
        self.email_service.send_email.assert_called_once_with(
            self.user.email,
            "Finish your ResearchHub profile",
            {"profile_url": f"{settings.BASE_FRONTEND_URL}/author/{author_id}"},
            template="complete_profile_email",
        )

    def test_skips_user_with_complete_profile(self):
        """A user with every profile field filled in is not emailed."""
        # Arrange
        author = self.user.author_profile
        author.profile_image = "uploads/author_profile_images/avatar.png"
        author.orcid_id = "https://orcid.org/0000-0000-0000-0000"
        author.twitter = "https://x.com/researcher"
        author.linkedin = "https://linkedin.com/in/researcher"
        author.google_scholar = "https://scholar.google.com/citations?user=abc"
        author.save()

        # Act
        self.service.send_if_eligible(self.user.id)

        # Assert
        self.email_service.send_email.assert_not_called()

    def test_sends_only_once_per_user(self):
        """A user who already received the email is not emailed again."""
        # Act
        self.service.send_if_eligible(self.user.id)
        self.service.send_if_eligible(self.user.id)

        # Assert
        self.email_service.send_email.assert_called_once()

    def test_emails_only_accounts_that_turned_a_week_old_in_the_last_day(self):
        """Only accounts created seven to eight days ago are emailed."""
        # Arrange
        too_new = create_random_default_user("too_new")
        too_old = create_random_default_user("too_old")
        self._set_date_joined(self.user, 7.5)
        self._set_date_joined(too_new, 3)
        self._set_date_joined(too_old, 10)

        # Act
        self.service.send_to_week_old_accounts()

        # Assert
        self.email_service.send_email.assert_called_once()
        recipient = self.email_service.send_email.call_args.args[0]
        self.assertEqual(recipient, self.user.email)


class QueueCompleteProfileEmailOnNotePublishTests(TestCase):
    @patch(
        "user.signals.complete_profile_email_signals.send_complete_profile_email_task"
    )
    def test_queues_email_when_note_is_published(self, mock_task):
        """Publishing a notebook note queues the email for its author on commit."""
        # Arrange
        post = Mock(spec=ResearchhubPost, note_id=1, created_by_id=7)

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            queue_complete_profile_email_on_note_publish(
                ResearchhubPost, instance=post, created=True
            )

        # Assert
        mock_task.delay.assert_called_once_with(7)
