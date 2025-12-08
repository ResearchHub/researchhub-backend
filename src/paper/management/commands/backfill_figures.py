"""
Management command to backfill figure extraction for existing papers.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from paper.models import Figure, Paper
from paper.tasks import extract_pdf_figures


class Command(BaseCommand):
    help = "Backfill figure extraction for papers that have PDFs but no figures"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of papers to process (default: 100)",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run extraction asynchronously (via Celery)",
        )
        parser.add_argument(
            "--paper-ids",
            type=str,
            help="Comma-separated list of paper IDs to process",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without actually running",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        dry_run = options["dry_run"]

        # Build query
        if options["paper_ids"]:
            paper_ids = [int(id.strip()) for id in options["paper_ids"].split(",")]
            papers = Paper.objects.filter(id__in=paper_ids, file__isnull=False)
        else:
            # Find papers with PDFs but no figures
            papers = (
                Paper.objects.filter(file__isnull=False)
                .exclude(
                    Q(figures__figure_type=Figure.FIGURE) | Q(figures__isnull=False)
                )
                .distinct()[:limit]
            )

        paper_count = papers.count()

        if paper_count == 0:
            self.stdout.write(self.style.WARNING("No papers found to process"))
            return

        self.stdout.write(f"\nFound {paper_count} papers to process\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made\n"))
            for paper in papers:
                self.stdout.write(f"  - Paper {paper.id}: {paper.title[:60]}...")
            return

        processed = 0
        failed = 0

        for paper in papers:
            try:
                self.stdout.write(f"Processing paper {paper.id}...", ending=" ")

                if options["async"]:
                    extract_pdf_figures.apply_async((paper.id,), priority=6)
                    self.stdout.write(self.style.SUCCESS("queued"))
                else:
                    result = extract_pdf_figures(paper.id)
                    if result:
                        figures_count = Figure.objects.filter(
                            paper=paper, figure_type=Figure.FIGURE
                        ).count()
                        self.stdout.write(
                            self.style.SUCCESS(f"✓ ({figures_count} figures)")
                        )
                    else:
                        self.stdout.write(self.style.ERROR("✗ failed"))
                        failed += 1

                processed += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ error: {e}"))
                failed += 1

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Processed: {processed}")
        self.stdout.write(f"Failed: {failed}")
        self.stdout.write("=" * 60)

