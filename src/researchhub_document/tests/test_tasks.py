from datetime import timedelta
from unittest.mock import MagicMock, Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from discussion.models import Flag
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchJourney
from researchhub_document.tasks import (
    assign_preregistration_dois,
    send_proposal_entered_journal_email,
)
from user.tests.helpers import create_random_default_user


class AssignPreregistrationDoisTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("doi_test_user")

    def _create_post(
        self, document_type="PREREGISTRATION", days_old=10, doi=None, is_removed=False
    ):
        post = create_post(
            title="Test Post",
            created_by=self.user,
            document_type=document_type,
        )
        post.doi = doi
        post.created_date = timezone.now() - timedelta(days=days_old)
        post.save(update_fields=["doi", "created_date"])

        if is_removed:
            post.unified_document.is_removed = True
            post.unified_document.save(update_fields=["is_removed"])

        return post

    def _build_mock_doi(self, doi_value="10.55277/test123", status_code=200):
        mock = MagicMock()
        mock.doi = doi_value
        mock.register_doi_for_post.return_value = MagicMock(status_code=status_code)
        return mock

    @patch("researchhub_document.tasks.DOI")
    def test_assigns_doi_to_eligible_preregistrations(self, mock_doi_cls):
        mock_doi_cls.return_value = self._build_mock_doi("10.55277/doi1")
        preregistration = self._create_post("PREREGISTRATION", days_old=10)

        assign_preregistration_dois()

        preregistration.refresh_from_db()
        self.assertEqual(preregistration.doi, "10.55277/doi1")

    @patch("researchhub_document.tasks.DOI")
    def test_skips_ineligible_posts(self, mock_doi_cls):
        """
        Preregistrations that are too young, already have a DOI, are removed,
        or are flagged should be skipped. Non-preregistration types are always skipped.
        """
        self._create_post(days_old=3)
        self._create_post(days_old=10, doi="10.55277/existing")
        self._create_post(days_old=10, is_removed=True)
        self._create_post(document_type="DISCUSSION", days_old=10)
        self._create_post(document_type="GRANT", days_old=10)
        self._create_post(document_type="QUESTION", days_old=10)

        flagged = self._create_post(days_old=10)
        ct = ContentType.objects.get_for_model(flagged)
        Flag.objects.create(
            content_type=ct,
            object_id=flagged.id,
            created_by=create_random_default_user("flagger"),
            reason="spam",
        )

        # Act
        assign_preregistration_dois()

        # Assert
        mock_doi_cls.assert_not_called()

    @patch("researchhub_document.tasks.DOI")
    def test_handles_crossref_failure_and_continues(self, mock_doi_cls):
        # Arrange
        self._create_post(days_old=10)
        self._create_post(days_old=14)

        failing_doi = self._build_mock_doi("10.55277/fail")
        failing_doi.register_doi_for_post.side_effect = RuntimeError("Network error")
        success_doi = self._build_mock_doi("10.55277/ok")
        mock_doi_cls.side_effect = [failing_doi, success_doi]

        # Act
        assign_preregistration_dois()

        # Assert
        from researchhub_document.models import ResearchhubPost

        posts = ResearchhubPost.objects.filter(document_type="PREREGISTRATION")
        assigned = posts.exclude(doi__isnull=True).count()
        unassigned = posts.filter(doi__isnull=True).count()
        self.assertEqual(assigned, 1)
        self.assertEqual(unassigned, 1)


class SendProposalEnteredJournalEmailTests(TestCase):
    """Tests for the proposal-entered-journal email task."""

    def setUp(self) -> None:
        """Create a proposal author for each email task test."""
        self.user = create_random_default_user("journal_email_user")

    @patch("researchhub_document.tasks.send_email")
    def test_sends_email_for_journal_journey(self, mock_send_email: Mock) -> None:
        """Verify the task sends the journal entry email to the author."""
        # Arrange
        proposal = self._create_proposal()
        journey = self._create_journal_journey(proposal)
        mock_send_email.return_value = {"success": [self.user.email], "failure": []}

        # Act
        result = send_proposal_entered_journal_email(journey.id)

        # Assert
        self.assertEqual(result, mock_send_email.return_value)
        mock_send_email.assert_called_once()
        recipients, text_template, subject, context = mock_send_email.call_args[0][:4]
        self.assertEqual(recipients, [self.user.email])
        self.assertEqual(text_template, "general_email_message.txt")
        self.assertEqual(subject, "Your proposal is now in the ResearchHub Journal")
        self.assertEqual(context["subject"], subject)
        self.assertEqual(
            context["action"]["cta_label"],
            "Create Registered Report",
        )
        self.assertEqual(
            context["action"]["frontend_view_link"],
            proposal.unified_document.frontend_view_link(),
        )
        self.assertIn(proposal.title, context["action"]["message"])
        self.assertEqual(
            mock_send_email.call_args.kwargs["html_template"],
            "general_email_message.html",
        )

    @patch("researchhub_document.tasks.send_email")
    def test_skips_email_for_missing_journey(self, mock_send_email: Mock) -> None:
        """Verify the task skips email when the journey does not exist."""
        # Arrange
        missing_journey_id = 999999

        # Act
        result = send_proposal_entered_journal_email(missing_journey_id)

        # Assert
        self.assertIsNone(result)
        mock_send_email.assert_not_called()

    @patch("researchhub_document.tasks.send_email")
    def test_skips_email_for_journey_outside_journal(
        self, mock_send_email: Mock
    ) -> None:
        """Verify the task skips email until the journey enters the journal."""
        # Arrange
        proposal = self._create_proposal()
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
            is_in_journal=False,
        )

        # Act
        result = send_proposal_entered_journal_email(journey.id)

        # Assert
        self.assertIsNone(result)
        mock_send_email.assert_not_called()

    def _create_proposal(self) -> ResearchhubPost:
        """Create a preregistration post owned by the email recipient."""
        return create_post(
            title="Journal Email Proposal",
            created_by=self.user,
            document_type="PREREGISTRATION",
        )

    def _create_journal_journey(self, proposal: ResearchhubPost) -> ResearchJourney:
        """Create an in-journal journey for the proposal."""
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
            is_in_journal=True,
            journal_included_date=timezone.now(),
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        return journey
