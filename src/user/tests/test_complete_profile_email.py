from datetime import timedelta
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from mailing_list.models import EmailOptOut
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import Author, User
from user.services.complete_profile_email_service import CompleteProfileEmailService
from user.signals.complete_profile_email_signals import (
    queue_complete_profile_email_on_note_publish,
)
from user.tests.helpers import create_random_default_user


class CompleteProfileEmailServiceTests(TestCase):
    def setUp(self):
        self.email_service = Mock()
        self.email_service.send_email.return_value = 1
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

    def test_skips_user_without_author_profile(self):
        """A user with no author profile is not emailed."""
        # Arrange
        Author.objects.filter(user=self.user).update(user=None)

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

    def test_retries_user_when_email_is_not_accepted(self):
        """A send the backend does not accept leaves the user eligible again."""
        # Arrange
        self.email_service.send_email.return_value = 0

        # Act
        self.service.send_if_eligible(self.user.id)
        self.service.send_if_eligible(self.user.id)

        # Assert
        self.assertEqual(self.email_service.send_email.call_count, 2)

    def test_marks_opted_out_user_without_emailing(self):
        """An opted-out user is marked as handled so later runs skip them."""
        # Arrange
        EmailOptOut.add(self.user.email)

        # Act
        self.service.send_if_eligible(self.user.id)

        # Assert
        self.email_service.send_email.assert_not_called()
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.complete_profile_email_sent_date)

    def test_emails_week_old_accounts_within_catch_up_window(self):
        """Accounts one to two weeks old are emailed, so missed sweeps catch up."""
        # Arrange
        overdue = create_random_default_user("overdue")
        too_new = create_random_default_user("too_new")
        too_old = create_random_default_user("too_old")
        self._set_date_joined(self.user, 7.5)
        self._set_date_joined(overdue, 10)
        self._set_date_joined(too_new, 3)
        self._set_date_joined(too_old, 15)

        # Act
        self.service.send_to_week_old_accounts()

        # Assert
        recipients = {
            call.args[0] for call in self.email_service.send_email.call_args_list
        }
        self.assertEqual(recipients, {self.user.email, overdue.email})

    def test_continues_batch_when_one_user_fails(self):
        """An error for one user does not stop the rest of the daily batch."""
        # Arrange
        failing = create_random_default_user("failing")
        self._set_date_joined(self.user, 8)
        self._set_date_joined(failing, 8)

        def send_email(recipient, *args, **kwargs):
            if recipient == failing.email:
                raise RuntimeError("template failed to render")
            return 1

        self.email_service.send_email.side_effect = send_email

        # Act
        with self.assertLogs(
            "user.services.complete_profile_email_service", level="ERROR"
        ):
            self.service.send_to_week_old_accounts()

        # Assert
        self.user.refresh_from_db()
        failing.refresh_from_db()
        self.assertIsNotNone(self.user.complete_profile_email_sent_date)
        self.assertIsNone(failing.complete_profile_email_sent_date)


class CompleteProfileEmailTemplateTests(SimpleTestCase):
    def test_renders_profile_link_with_inlined_styles(self):
        """The CTA links to the profile, styled by both email stylesheets."""
        # Act
        html = render_to_string(
            "complete_profile_email.html",
            {
                "assets_base_url": "https://assets.example.com",
                "profile_url": "https://www.researchhub.com/author/1",
            },
        )

        # Assert
        soup = BeautifulSoup(html, "html.parser")
        cta = soup.find("a", href="https://www.researchhub.com/author/1")
        self.assertIn("padding: 13px 28px", cta["style"])
        tagline = soup.find(class_="profile-tagline")
        self.assertIn("max-width: 448px", tagline["style"])


@patch("user.signals.complete_profile_email_signals.send_complete_profile_email_task")
class QueueCompleteProfileEmailOnNotePublishTests(TestCase):
    def setUp(self):
        self.author = Mock(id=7, complete_profile_email_sent_date=None)
        self.post = Mock(spec=ResearchhubPost, note_id=1, created_by=self.author)

    def test_queues_email_when_note_is_published(self, mock_task):
        """Publishing a notebook note queues the email for its author on commit."""
        # Act
        with self.captureOnCommitCallbacks(execute=True):
            queue_complete_profile_email_on_note_publish(
                ResearchhubPost, instance=self.post, created=True
            )

        # Assert
        mock_task.delay.assert_called_once_with(7)

    def test_skips_author_already_emailed(self, mock_task):
        """An author who was already emailed does not queue another task."""
        # Arrange
        self.author.complete_profile_email_sent_date = timezone.now()

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            queue_complete_profile_email_on_note_publish(
                ResearchhubPost, instance=self.post, created=True
            )

        # Assert
        mock_task.delay.assert_not_called()

    def test_swallows_enqueue_failure(self, mock_task):
        """A broker outage does not fail the request that published the note."""
        # Arrange
        mock_task.delay.side_effect = ConnectionError("broker unavailable")

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            queue_complete_profile_email_on_note_publish(
                ResearchhubPost, instance=self.post, created=True
            )

        # Assert
        mock_task.delay.assert_called_once_with(7)
