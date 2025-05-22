from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import TransactionTestCase

from hub.models import Hub
from paper.related_models.paper_model import Paper, PaperVersion
from paper.tests.helpers import create_paper
from purchase.related_models.payment_model import Payment
from user.tests.helpers import create_random_default_user


class UpdatePaperJournalStatusSignalTest(TransactionTestCase):
    """Test the update_paper_journal_status signal handler."""

    def setUp(self):
        """Set up test data."""
        self.user = create_random_default_user("payment_test_user")
        self.paper = create_paper(uploaded_by=self.user)
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        Hub.objects.create(id=settings.RESEARCHHUB_JOURNAL_ID)

    def test_payment_for_paper_updates_journal_status(self):
        """Test that a payment for a paper updates its journal status."""
        # Create a PaperVersion for the test paper
        paper_version = PaperVersion.objects.create(
            paper=self.paper, version=1, publication_status=PaperVersion.PREPRINT
        )

        # Confirm initial state
        self.assertIsNone(paper_version.journal)

        # Create a payment for the paper
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
        self.assertEqual(self.paper.hubs.first().id, settings.RESEARCHHUB_JOURNAL_ID)

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
        """Test that when a paper has no version, an error is logged but no exception is raised."""
        # Make sure the paper has no version
        PaperVersion.objects.filter(paper=self.paper).delete()

        # Create a payment for the paper
        with patch("paper.signals.log_error") as mock_log_error:
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
