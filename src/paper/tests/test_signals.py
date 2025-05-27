from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import TransactionTestCase

from hub.models import Hub
from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from paper.related_models.paper_version import PaperVersion
from paper.tests.helpers import create_paper
from purchase.related_models.payment_model import Payment
from user.models import Author
from user.tests.helpers import create_random_default_user


class UpdatePaperJournalStatusSignalTest(TransactionTestCase):
    """Test the update_paper_journal_status signal handler."""

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "123")
    def setUp(self):
        """Set up test data."""
        self.user = create_random_default_user("payment_test_user")
        self.paper = create_paper(uploaded_by=self.user)
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        Hub.objects.create(id=123)

    def test_payment_for_paper_updates_journal_status(self):
        """Test that a payment for a paper updates its journal status."""
        # Create a PaperVersion for the test paper
        paper_version = PaperVersion.objects.create(
            paper=self.paper, version=1, publication_status=PaperVersion.PREPRINT
        )

        # Confirm initial state
        self.assertIsNone(paper_version.journal)

        # Create a payment for the paper
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "123"):
            Payment.objects.create(
                amount=1000,
                currency="USD",
                external_payment_id="test_payment_id",
                payment_processor="STRIPE",
                content_type=self.paper_content_type,
                object_id=self.paper.id,
                user=self.user,
            )

            # Verify the paper version was updated to be part of the ResearchHub journal
            paper_version.refresh_from_db()
            self.assertEqual(paper_version.journal, PaperVersion.RESEARCHHUB)

            # Verify that the ResearchHub Journal was added to the paper
            self.assertEqual(self.paper.hubs.count(), 1)
            self.assertEqual(self.paper.hubs.first().id, 123)

            # Verify that the publication status was not changed
            self.assertEqual(paper_version.publication_status, PaperVersion.PREPRINT)

    def test_payment_for_non_paper_doesnt_update_journal_status(self):
        """Test that a payment for a non-paper doesn't update any journal status."""
        # Create a PaperVersion for the test paper
        paper_version = PaperVersion.objects.create(paper=self.paper, version=1)

        # Confirm initial state
        self.assertIsNone(paper_version.journal)

        # Create a payment for something else (different content type)
        other_content_type = ContentType.objects.get_for_model(PaperVersion)
        Payment.objects.create(
            amount=1000,
            currency="USD",
            external_payment_id="test_payment_id",
            payment_processor="STRIPE",
            content_type=other_content_type,
            object_id=paper_version.id,
            user=self.user,
        )

        # Verify the paper version was not updated
        paper_version.refresh_from_db()
        self.assertIsNone(paper_version.journal)

    def test_paper_without_version_logs_error(self):
        """
        Test that when a paper has no version, an error is logged
        but no exception is raised.
        """
        # Make sure the paper has no version
        PaperVersion.objects.filter(paper=self.paper).delete()

        # Create a payment for the paper
        with patch("paper.signals.log_error") as mock_log_error:
            with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "123"):
                Payment.objects.create(
                    amount=1000,
                    currency="USD",
                    external_payment_id="test_payment_id",
                    payment_processor="STRIPE",
                    content_type=self.paper_content_type,
                    object_id=self.paper.id,
                    user=self.user,
                )

            # Verify an error was logged
            mock_log_error.assert_called_once()
            error_msg = mock_log_error.call_args[0][0]
            self.assertIn(f"No PaperVersion found for paper {self.paper.id}", error_msg)

    def test_update_existing_paper_version(self):
        """Test updating an existing paper version."""
        # Create a paper version that's already part of another journal
        paper_version = PaperVersion.objects.create(
            paper=self.paper, version=1, journal="OTHER_JOURNAL"  # Some other journal
        )

        # Create a payment for the paper
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "123"):
            Payment.objects.create(
                amount=1000,
                currency="USD",
                external_payment_id="test_payment_id",
                payment_processor="STRIPE",
                content_type=self.paper_content_type,
                object_id=self.paper.id,
                user=self.user,
            )

        # Verify the paper version was updated to be part of the ResearchHub journal
        paper_version.refresh_from_db()
        self.assertEqual(paper_version.journal, PaperVersion.RESEARCHHUB)

    @patch("paper.signals.DOI")
    def test_payment_creates_doi_for_paper(self, mock_doi_class):
        """Test that a payment for a paper creates a new DOI."""
        # Create an author and authorship for the paper
        author = Author.objects.create(first_name="Test", last_name="Author")
        Authorship.objects.create(paper=self.paper, author=author)

        # Create a PaperVersion for the test paper
        paper_version = PaperVersion.objects.create(
            paper=self.paper, version=1, publication_status=PaperVersion.PREPRINT
        )

        # Mock the DOI class and its methods
        mock_doi_instance = MagicMock()
        mock_doi_instance.doi = "10.55277/rhj.test123.1"
        mock_doi_instance.base_doi = "10.55277/rhj.test123"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_doi_instance.register_doi_for_paper.return_value = mock_response

        mock_doi_class.return_value = mock_doi_instance

        # Confirm initial state - no DOI
        self.assertIsNone(self.paper.doi)
        self.assertIsNone(paper_version.base_doi)

        # Create a payment for the paper
        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "123"):
            Payment.objects.create(
                amount=1000,
                currency="USD",
                external_payment_id="test_payment_id",
                payment_processor="STRIPE",
                content_type=self.paper_content_type,
                object_id=self.paper.id,
                user=self.user,
            )

        # Verify DOI was created with correct journal parameter
        mock_doi_class.assert_called_once_with(
            base_doi=paper_version.base_doi,
            version=paper_version.version,
            journal=PaperVersion.RESEARCHHUB,
        )

        # Verify DOI registration was called with correct parameters
        mock_doi_instance.register_doi_for_paper.assert_called_once()
        call_args = mock_doi_instance.register_doi_for_paper.call_args
        self.assertEqual(len(call_args[1]["authors"]), 1)
        self.assertEqual(call_args[1]["authors"][0], author)
        self.assertEqual(call_args[1]["title"], self.paper.title)
        self.assertEqual(call_args[1]["rh_paper"], self.paper)

        # Verify the paper and paper version were updated with DOI
        self.paper.refresh_from_db()
        paper_version.refresh_from_db()
        self.assertEqual(self.paper.doi, "10.55277/rhj.test123.1")
        self.assertEqual(paper_version.base_doi, "10.55277/rhj.test123")

    @patch("paper.signals.DOI")
    def test_payment_handles_doi_registration_failure(self, mock_doi_class):
        """Test that DOI registration failure is handled gracefully."""
        # Create an author and authorship for the paper
        author = Author.objects.create(first_name="Test", last_name="Author")
        Authorship.objects.create(paper=self.paper, author=author)

        # Create a PaperVersion for the test paper
        paper_version = PaperVersion.objects.create(
            paper=self.paper, version=1, publication_status=PaperVersion.PREPRINT
        )

        # Mock the DOI class with failed registration
        mock_doi_instance = MagicMock()
        mock_doi_instance.doi = "10.55277/rhj.test123.1"
        mock_doi_instance.base_doi = "10.55277/rhj.test123"
        mock_response = MagicMock()
        mock_response.status_code = 400  # Failed registration
        mock_doi_instance.register_doi_for_paper.return_value = mock_response

        mock_doi_class.return_value = mock_doi_instance

        # Create a payment for the paper
        with patch("paper.signals.log_error") as mock_log_error:
            with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "123"):
                Payment.objects.create(
                    amount=1000,
                    currency="USD",
                    external_payment_id="test_payment_id",
                    payment_processor="STRIPE",
                    content_type=self.paper_content_type,
                    object_id=self.paper.id,
                    user=self.user,
                )

        # Verify error was logged for failed DOI registration
        mock_log_error.assert_called()
        error_calls = [call[0][0] for call in mock_log_error.call_args_list]
        self.assertTrue(any("Failed to register DOI" in call for call in error_calls))

        # Verify the paper and paper version were NOT updated with DOI
        self.paper.refresh_from_db()
        paper_version.refresh_from_db()
        self.assertIsNone(self.paper.doi)
        self.assertIsNone(paper_version.base_doi)
