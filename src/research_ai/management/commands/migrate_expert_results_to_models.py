"""
Backfill ``Expert`` and ``SearchExpert`` from legacy ``ExpertSearch.expert_results``.

Uses ``expert_results_legacy_migration`` (MIGRATION-ONLY heuristics) and
``ExpertPersist.replace_search_experts_for_search``. Safe to re-run with
``--force-replace``; default skips searches that already have ``SearchExpert`` rows.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from research_ai.models import ExpertSearch
from research_ai.services.expert_persist import ExpertPersist
from research_ai.services.expert_results_legacy_migration import (
    legacy_expert_results_to_persist_rows,
)


class Command(BaseCommand):
    help = (
        "Backfill Expert + SearchExpert rows from ExpertSearch.expert_results JSON. "
        "Skips searches with no expert_results rows. By default skips searches that "
        "already have SearchExpert links unless --force-replace is set."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts and actions without writing to the database.",
        )
        parser.add_argument(
            "--force-replace",
            action="store_true",
            help="Replace SearchExpert links from expert_results even if links already exist.",
        )
        parser.add_argument(
            "--search-id",
            type=int,
            default=None,
            help="Only process the given ExpertSearch primary key.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process at most this many searches (stable order by id ascending).",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        force_replace: bool = options["force_replace"]
        search_id: int | None = options["search_id"]
        limit: int | None = options["limit"]

        qs = ExpertSearch.objects.annotate(
            _se_count=Count("search_experts", distinct=True)
        ).order_by("id")

        if search_id is not None:
            qs = qs.filter(id=search_id)

        if not force_replace:
            qs = qs.filter(_se_count=0)

        candidates = []
        for search in qs.iterator():
            raw = search.expert_results
            if not isinstance(raw, list) or len(raw) == 0:
                continue
            rows = legacy_expert_results_to_persist_rows(raw)
            if not rows:
                continue
            candidates.append((search, rows))
            if limit is not None and len(candidates) >= limit:
                break

        self.stdout.write(
            f"Searches to migrate: {len(candidates)} "
            f"(dry_run={dry_run}, force_replace={force_replace})"
        )

        if dry_run:
            for search, rows in candidates:
                self.stdout.write(
                    f"  would migrate search_id={search.id} "
                    f"legacy_items={len(search.expert_results)} "
                    f"valid_rows={len(rows)}"
                )
            self.stdout.write(self.style.WARNING("Dry run — no database writes."))
            return

        migrated = 0
        experts_linked = 0
        for search, rows in candidates:
            n = ExpertPersist.replace_search_experts_for_search(search.id, rows)
            migrated += 1
            experts_linked += n
            self.stdout.write(
                self.style.SUCCESS(
                    f"migrated search_id={search.id} search_expert_rows={n}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Searches migrated: {migrated}, SearchExpert rows written: {experts_linked}."
            )
        )
