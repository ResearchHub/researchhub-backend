from __future__ import annotations

from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Min, Q, QuerySet
from django.utils import timezone

from purchase.models import Fundraise
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.services.journey_service import JourneyService


class Command(BaseCommand):
    help = "Backfill research journeys and journal inclusion for existing proposals."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add command-line arguments for the backfill."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Count eligible rows without creating or updating journeys.",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=500,
            help="Number of proposals to process per database chunk.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Run the research journey backfill."""
        dry_run = bool(options["dry_run"])
        chunk_size = int(options["chunk_size"])
        service = JourneyService()

        journey_stats = self.create_journeys(
            service,
            self.get_approved_proposals(),
            chunk_size,
            dry_run,
        )
        journal_stats = self.include_funded_journeys(
            service,
            self.get_funded_proposals(),
            chunk_size,
            dry_run,
        )

        self.write_summary(journey_stats, journal_stats, dry_run)

    def get_approved_proposals(self) -> QuerySet[ResearchhubPost]:
        """Return approved preregistration posts eligible for journey anchors."""
        return (
            ResearchhubPost.objects.filter(
                document_type=PREREGISTRATION,
                unified_document__is_removed=False,
                unified_document__status=ResearchhubUnifiedDocument.APPROVED,
            )
            .select_related("journey", "unified_document")
            .order_by("id")
        )

    def get_funded_proposals(self) -> QuerySet[ResearchhubPost]:
        """Return approved preregistrations with completed fundraises."""
        return (
            self.get_approved_proposals()
            .filter(unified_document__fundraises__status=Fundraise.COMPLETED)
            .annotate(
                completed_fundraise_date=Min(
                    "unified_document__fundraises__updated_date",
                    filter=Q(
                        unified_document__fundraises__status=Fundraise.COMPLETED
                    ),
                )
            )
            .distinct()
        )

    def create_journeys(
        self,
        service: JourneyService,
        proposals: QuerySet[ResearchhubPost],
        chunk_size: int,
        dry_run: bool,
    ) -> dict[str, int]:
        """Create or complete journey links for approved proposals."""
        stats = {"processed": 0, "changed": 0, "errors": 0}
        for proposal in proposals.iterator(chunk_size=chunk_size):
            stats["processed"] += 1
            if dry_run:
                if not self.has_complete_journey(proposal):
                    stats["changed"] += 1
                continue

            try:
                had_complete_journey = self.has_complete_journey(proposal)
                self.get_or_create_journey(service, proposal)
                if not had_complete_journey:
                    stats["changed"] += 1
            except Exception as error:
                stats["errors"] += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Failed to backfill journey for proposal {proposal.id}: "
                        f"{error}"
                    )
                )
        return stats

    def include_funded_journeys(
        self,
        service: JourneyService,
        proposals: QuerySet[ResearchhubPost],
        chunk_size: int,
        dry_run: bool,
    ) -> dict[str, int]:
        """Mark funded proposal journeys as included in the journal."""
        stats = {"processed": 0, "changed": 0, "errors": 0}
        for proposal in proposals.iterator(chunk_size=chunk_size):
            stats["processed"] += 1
            if dry_run:
                if not self.has_journal_inclusion(proposal):
                    stats["changed"] += 1
                continue

            try:
                included_date = (
                    getattr(proposal, "completed_fundraise_date", None)
                    or timezone.now()
                )
                journey = self.get_or_create_journey(service, proposal)
                if self.mark_journey_in_journal(journey, included_date):
                    stats["changed"] += 1
            except Exception as error:
                stats["errors"] += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Failed to include proposal {proposal.id} in journal: "
                        f"{error}"
                    )
                )
        return stats

    def get_or_create_journey(
        self, service: JourneyService, proposal: ResearchhubPost
    ) -> ResearchJourney:
        """Return the proposal journey, creating or completing links as needed."""
        if proposal.journey_id is not None:
            service.attach_stage(proposal.journey, proposal)
            return proposal.journey
        return service.get_or_create_for_preregistration(proposal)

    def has_complete_journey(self, proposal: ResearchhubPost) -> bool:
        """Return whether the proposal and journey point to each other."""
        journey = getattr(proposal, "journey", None)
        return journey is not None and journey.preregistration_post_id == proposal.id

    def has_journal_inclusion(self, proposal: ResearchhubPost) -> bool:
        """Return whether the proposal's journey is fully journal-included."""
        journey = getattr(proposal, "journey", None)
        return (
            journey is not None
            and journey.is_in_journal
            and journey.journal_included_date is not None
        )

    def mark_journey_in_journal(
        self, journey: ResearchJourney, included_date: datetime
    ) -> bool:
        """Persist journal inclusion fields without sending notifications."""
        update_fields = []
        if not journey.is_in_journal:
            journey.is_in_journal = True
            update_fields.append("is_in_journal")
        if journey.journal_included_date is None:
            journey.journal_included_date = included_date
            update_fields.append("journal_included_date")
        if not update_fields:
            return False

        journey.save(update_fields=update_fields)
        return True

    def write_summary(
        self,
        journey_stats: dict[str, int],
        journal_stats: dict[str, int],
        dry_run: bool,
    ) -> None:
        """Write the backfill summary to stdout."""
        mode = "DRY RUN" if dry_run else "DONE"
        self.stdout.write(
            f"{mode}: journeys processed={journey_stats['processed']} "
            f"changed={journey_stats['changed']} errors={journey_stats['errors']}"
        )
        self.stdout.write(
            f"{mode}: funded proposals processed={journal_stats['processed']} "
            f"changed={journal_stats['changed']} errors={journal_stats['errors']}"
        )
