from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from researchhub_document.services.research_journey_backfill_service import (
    ResearchJourneyBackfillService,
    ResearchJourneyBackfillStats,
)


class Command(BaseCommand):
    """Backfill journeys for existing approved preregistration proposals."""

    help = "Backfill research journeys and journal inclusion for existing proposals."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add command-line arguments for the backfill."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
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
        if chunk_size < 1:
            raise CommandError("--chunk-size must be at least 1.")

        stats = ResearchJourneyBackfillService().backfill(
            chunk_size=chunk_size,
            dry_run=dry_run,
        )
        self._write_failures(stats)
        self._write_summary(stats, dry_run)
        if stats.has_failures:
            raise CommandError("Research journey backfill completed with errors.")

    def _write_failures(self, stats: ResearchJourneyBackfillStats) -> None:
        """Write recoverable proposal-level backfill failures to stderr."""
        for failure in stats.failures:
            self.stderr.write(
                self.style.ERROR(
                    f"Failed to backfill proposal {failure.proposal_id}: "
                    f"{failure.message}"
                )
            )

    def _write_summary(
        self,
        stats: ResearchJourneyBackfillStats,
        dry_run: bool,
    ) -> None:
        """Write the backfill summary to stdout."""
        mode = "DRY RUN" if dry_run else "DONE"
        self.stdout.write(
            f"{mode}: proposals processed={stats.proposals_processed} "
            f"journey changes={stats.journey_changes} "
            f"journal candidates={stats.journal_candidates_processed} "
            f"journal inclusion changes={stats.journal_inclusion_changes} "
            f"errors={len(stats.failures)}"
        )
