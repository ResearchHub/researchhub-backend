from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from notification.models import Notification
from purchase.models import Fundraise
from researchhub_document.helpers import create_post
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from user.tests.helpers import create_random_default_user


class BackfillResearchJourneysCommandTests(TestCase):
    def setUp(self) -> None:
        """Create a proposal author for each backfill command test."""
        self.user = create_random_default_user("journey_backfill_user")

    def test_backfills_journeys_for_approved_proposals(self) -> None:
        """Verify approved proposals receive journey anchors."""
        # Arrange
        approved_proposal = self.create_proposal()
        pending_proposal = self.create_proposal(
            status=ResearchhubUnifiedDocument.PENDING
        )

        # Act
        self.run_command()

        # Assert
        approved_proposal.refresh_from_db()
        pending_proposal.refresh_from_db()
        self.assertIsNotNone(approved_proposal.journey)
        self.assertEqual(
            approved_proposal.journey.preregistration_post,
            approved_proposal,
        )
        self.assertIsNone(pending_proposal.journey)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_includes_funded_journeys_without_sending_messages(self) -> None:
        """Verify funded proposal journeys enter the journal without messages."""
        # Arrange
        proposal = self.create_proposal()
        self.create_completed_fundraise(proposal)

        # Act
        with patch(
            "researchhub_document.management.commands.backfill_research_journeys."
            "JourneyService.notify_author_about_journal_entry"
        ) as notify_author:
            with patch(
                "researchhub_document.management.commands.backfill_research_journeys."
                "JourneyService.send_author_journal_entry_email"
            ) as email_author:
                self.run_command()

        # Assert
        proposal.refresh_from_db()
        journey = proposal.journey
        self.assertTrue(journey.is_in_journal)
        self.assertIsNotNone(journey.journal_included_date)
        notify_author.assert_not_called()
        email_author.assert_not_called()
        self.assertFalse(
            Notification.objects.filter(
                notification_type=Notification.PROPOSAL_ENTERED_JOURNAL,
                recipient=self.user,
            ).exists()
        )

    def test_preserves_existing_journal_included_date(self) -> None:
        """Verify existing journal inclusion dates are not overwritten."""
        # Arrange
        proposal = self.create_proposal()
        included_date = timezone.now()
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
            is_in_journal=True,
            journal_included_date=included_date,
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        self.create_completed_fundraise(proposal)

        # Act
        self.run_command()

        # Assert
        journey.refresh_from_db()
        self.assertEqual(journey.journal_included_date, included_date)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_does_not_change_data_during_dry_run(self) -> None:
        """Verify dry-run mode leaves journeys unchanged."""
        # Arrange
        proposal = self.create_proposal()
        self.create_completed_fundraise(proposal)

        # Act
        self.run_command("--dry-run")

        # Assert
        proposal.refresh_from_db()
        self.assertIsNone(proposal.journey)
        self.assertFalse(ResearchJourney.objects.exists())

    def test_skips_removed_proposals(self) -> None:
        """Verify removed proposals do not receive journey anchors."""
        # Arrange
        proposal = self.create_proposal(is_removed=True)
        self.create_completed_fundraise(proposal)

        # Act
        self.run_command()

        # Assert
        proposal.refresh_from_db()
        self.assertIsNone(proposal.journey)
        self.assertFalse(ResearchJourney.objects.exists())

    def create_proposal(
        self,
        *,
        status: str = ResearchhubUnifiedDocument.APPROVED,
        is_removed: bool = False,
    ) -> ResearchhubPost:
        """Create a preregistration post for command tests."""
        proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Backfill proposal",
        )
        proposal.unified_document.status = status
        proposal.unified_document.is_removed = is_removed
        proposal.unified_document.save(update_fields=["status", "is_removed"])
        return proposal

    def create_completed_fundraise(self, proposal: ResearchhubPost) -> Fundraise:
        """Create a completed fundraise for a proposal."""
        return Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

    def run_command(self, *args: str) -> None:
        """Run the backfill command with captured output."""
        call_command("backfill_research_journeys", *args, stdout=StringIO())
