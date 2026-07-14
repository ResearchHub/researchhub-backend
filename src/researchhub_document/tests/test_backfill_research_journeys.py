from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from purchase.models import Fundraise, UsdFundraiseContribution
from reputation.models import Escrow
from researchhub_document.helpers import create_post
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_default_user


class BackfillResearchJourneysCommandTests(TestCase):
    """Verify the research journey backfill command."""

    def setUp(self) -> None:
        """Create a proposal author for each backfill command test."""
        self.user = create_random_default_user("journey_backfill_user")

    def test_backfills_journeys_for_approved_proposals(self) -> None:
        """Verify active approved proposals receive journey anchors."""
        # Arrange
        approved_proposal = self._create_proposal()
        pending_proposal = self._create_proposal(
            status=ResearchhubUnifiedDocument.PENDING
        )
        removed_proposal = self._create_proposal(is_removed=True)

        # Act
        self._run_command()

        # Assert
        approved_proposal.refresh_from_db()
        pending_proposal.refresh_from_db()
        removed_proposal.refresh_from_db()
        self.assertEqual(
            approved_proposal.journey.preregistration_post,
            approved_proposal,
        )
        self.assertIsNone(pending_proposal.journey)
        self.assertIsNone(removed_proposal.journey)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_repairs_incomplete_proposal_journey_links(self) -> None:
        """Verify a linked journey receives its missing proposal anchor."""
        # Arrange
        proposal = self._create_proposal()
        journey = ResearchJourney.objects.create()
        proposal.journey = journey
        proposal.save(update_fields=["journey"])

        # Act
        self._run_command()

        # Assert
        journey.refresh_from_db()
        self.assertEqual(journey.preregistration_post, proposal)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_includes_rsc_funded_proposals_at_backfill_time(self) -> None:
        """Verify funded proposals enter the journal when the backfill runs."""
        # Arrange
        proposal = self._create_proposal()
        fundraise = self._create_fundraise(
            proposal,
            status=Fundraise.COMPLETED,
            rsc_amount=Decimal("100.00"),
        )
        Fundraise.objects.filter(id=fundraise.id).update(
            updated_date=timezone.now() - timedelta(days=1)
        )
        before_backfill = timezone.now()

        # Act
        self._run_command()

        # Assert
        proposal.refresh_from_db()
        journey = proposal.journey
        self.assertTrue(journey.is_in_journal)
        self.assertGreaterEqual(journey.journal_included_date, before_backfill)

    def test_includes_usd_funded_proposals_in_journal(self) -> None:
        """Verify non-refunded USD funding makes proposals journal eligible."""
        # Arrange
        proposal = self._create_proposal()
        fundraise = self._create_fundraise(
            proposal,
            status=Fundraise.COMPLETED,
        )
        self._create_usd_contribution(fundraise)

        # Act
        self._run_command()

        # Assert
        proposal.refresh_from_db()
        self.assertTrue(proposal.journey.is_in_journal)

    def test_skips_ineligible_proposals_for_journal_inclusion(self) -> None:
        """Verify only funded completed proposals enter the journal."""
        # Arrange
        open_proposal = self._create_proposal()
        unfunded_proposal = self._create_proposal()
        refunded_proposal = self._create_proposal()
        self._create_fundraise(
            open_proposal,
            status=Fundraise.OPEN,
            rsc_amount=Decimal("100.00"),
        )
        self._create_fundraise(
            unfunded_proposal,
            status=Fundraise.COMPLETED,
        )
        refunded_fundraise = self._create_fundraise(
            refunded_proposal,
            status=Fundraise.COMPLETED,
        )
        self._create_usd_contribution(refunded_fundraise, is_refunded=True)

        # Act
        self._run_command()

        # Assert
        open_proposal.refresh_from_db()
        unfunded_proposal.refresh_from_db()
        refunded_proposal.refresh_from_db()
        self.assertFalse(open_proposal.journey.is_in_journal)
        self.assertFalse(unfunded_proposal.journey.is_in_journal)
        self.assertFalse(refunded_proposal.journey.is_in_journal)

    def test_preserves_existing_journal_included_date(self) -> None:
        """Verify existing journal inclusion dates are not overwritten."""
        # Arrange
        proposal = self._create_proposal()
        included_date = timezone.now() - timedelta(days=2)
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
            is_in_journal=True,
            journal_included_date=included_date,
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        self._create_fundraise(
            proposal,
            status=Fundraise.COMPLETED,
            rsc_amount=Decimal("100.00"),
        )

        # Act
        self._run_command()

        # Assert
        journey.refresh_from_db()
        self.assertEqual(journey.journal_included_date, included_date)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_reruns_backfill_without_changes(self) -> None:
        """Verify a completed backfill is idempotent."""
        # Arrange
        proposal = self._create_proposal()
        self._create_fundraise(
            proposal,
            status=Fundraise.COMPLETED,
            rsc_amount=Decimal("100.00"),
        )
        self._run_command()
        proposal.refresh_from_db()
        included_date = proposal.journey.journal_included_date

        # Act
        output = self._run_command()

        # Assert
        proposal.journey.refresh_from_db()
        self.assertEqual(proposal.journey.journal_included_date, included_date)
        self.assertIn(
            "DONE: proposals processed=1 journey changes=0 journal candidates=1 "
            "journal inclusion changes=0 errors=0",
            output,
        )

    def test_does_not_change_data_during_dry_run(self) -> None:
        """Verify dry-run mode reports changes without persisting them."""
        # Arrange
        proposal = self._create_proposal()
        self._create_fundraise(
            proposal,
            status=Fundraise.COMPLETED,
            rsc_amount=Decimal("100.00"),
        )

        # Act
        output = self._run_command("--dry-run")

        # Assert
        proposal.refresh_from_db()
        self.assertIsNone(proposal.journey)
        self.assertFalse(ResearchJourney.objects.exists())
        self.assertIn(
            "DRY RUN: proposals processed=1 journey changes=1 "
            "journal candidates=1 journal inclusion changes=1 errors=0",
            output,
        )

    def test_uses_newest_completed_fundraise_for_journal_eligibility(self) -> None:
        """Verify an unfunded newer fundraise prevents journal inclusion."""
        # Arrange
        proposal = self._create_proposal()
        funded_fundraise = self._create_fundraise(
            proposal,
            status=Fundraise.COMPLETED,
            rsc_amount=Decimal("100.00"),
        )
        Fundraise.objects.filter(id=funded_fundraise.id).update(
            created_date=timezone.now() - timedelta(days=1)
        )
        self._create_fundraise(
            proposal,
            status=Fundraise.COMPLETED,
        )

        # Act
        self._run_command()

        # Assert
        proposal.refresh_from_db()
        self.assertFalse(proposal.journey.is_in_journal)

    def test_rejects_non_positive_chunk_size(self) -> None:
        """Verify the command rejects chunk sizes that cannot be iterated."""
        # Arrange
        chunk_size = 0

        # Act / Assert
        with self.assertRaisesMessage(
            CommandError,
            "--chunk-size must be at least 1.",
        ):
            self._run_command("--chunk-size", str(chunk_size))

    def test_reports_invalid_journey_links_as_command_errors(self) -> None:
        """Verify invalid journey data makes the command fail after reporting it."""
        # Arrange
        proposal = self._create_proposal()
        pending_proposal = self._create_proposal(
            status=ResearchhubUnifiedDocument.PENDING
        )
        conflicting_journey = ResearchJourney.objects.create(
            preregistration_post=pending_proposal,
        )
        proposal.journey = conflicting_journey
        proposal.save(update_fields=["journey"])
        errors = StringIO()

        # Act / Assert
        with self.assertRaisesMessage(
            CommandError,
            "Research journey backfill completed with errors.",
        ):
            self._run_command(stderr=errors)

        # Assert
        self.assertIn(
            "Failed to backfill proposal "
            f"{proposal.id}: Journey already has a proposal.",
            errors.getvalue(),
        )

    def _create_proposal(
        self,
        *,
        status: str = ResearchhubUnifiedDocument.APPROVED,
        is_removed: bool = False,
    ) -> ResearchhubPost:
        """Create a preregistration proposal with the requested eligibility."""
        proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Backfill proposal",
        )
        proposal.unified_document.status = status
        proposal.unified_document.is_removed = is_removed
        proposal.unified_document.save(update_fields=["status", "is_removed"])
        return proposal

    def _create_fundraise(
        self,
        proposal: ResearchhubPost,
        *,
        status: str,
        rsc_amount: Decimal | None = None,
    ) -> Fundraise:
        """Create a fundraise with optional escrowed RSC funding."""
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=status,
        )
        if rsc_amount is None:
            return fundraise

        fundraise.escrow = Escrow.objects.create(
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=rsc_amount,
        )
        fundraise.save(update_fields=["escrow"])
        return fundraise

    def _create_usd_contribution(
        self, fundraise: Fundraise, *, is_refunded: bool = False
    ) -> UsdFundraiseContribution:
        """Create a USD contribution with the requested refund status."""
        return UsdFundraiseContribution.objects.create(
            user=self.user,
            fundraise=fundraise,
            amount_cents=1000,
            is_refunded=is_refunded,
            origin_fund_id="origin-fund",
            destination_org_id="destination-organization",
        )

    def _run_command(
        self,
        *args: str,
        stderr: StringIO | None = None,
    ) -> str:
        """Run the backfill command and return its standard output."""
        output = StringIO()
        command_options: dict[str, StringIO] = {"stdout": output}
        if stderr is not None:
            command_options["stderr"] = stderr
        call_command("backfill_research_journeys", *args, **command_options)
        return output.getvalue()
