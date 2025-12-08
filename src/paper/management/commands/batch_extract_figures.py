"""
Management command to extract figures for multiple papers in batch.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from paper.models import Figure, Paper
from paper.tasks import extract_pdf_figures


class Command(BaseCommand):
    help = "Extract figures for multiple papers in batch"

    def add_arguments(self, parser):
        parser.add_argument(
            "--paper-ids",
            type=str,
            help="Comma-separated list of paper IDs to process",
        )
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
            "--has-pdf-only",
            action="store_true",
            help="Only process papers that have PDF files",
        )
        parser.add_argument(
            "--no-figures-only",
            action="store_true",
            help="Only process papers that don't have extracted figures yet",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without actually running",
        )

    def handle(self, *args, **options):
        # Build query
        if options["paper_ids"]:
            paper_ids = [int(id.strip()) for id in options["paper_ids"].split(",")]
            papers = Paper.objects.filter(id__in=paper_ids)
        else:
            papers = Paper.objects.all()

        # Apply filters
        if options["has_pdf_only"]:
            papers = papers.filter(file__isnull=False)

        if options["no_figures_only"]:
            papers = papers.exclude(
                Q(figures__figure_type=Figure.FIGURE) | Q(figures__isnull=False)
            ).distinct()

        # Apply limit
        papers = papers[: options["limit"]]

        paper_count = papers.count()

        if paper_count == 0:
            self.stdout.write(self.style.WARNING("No papers found to process"))
            return

        self.stdout.write(f"\nFound {paper_count} papers to process\n")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made\n"))
            for paper in papers:
                has_pdf = "✓" if paper.file else "✗"
                has_figures = (
                    "✓"
                    if Figure.objects.filter(
                        paper=paper, figure_type=Figure.FIGURE
                    ).exists()
                    else "✗"
                )
                self.stdout.write(
                    f"  - Paper {paper.id}: {paper.title[:60]}... "
                    f"[PDF: {has_pdf}, Figures: {has_figures}]"
                )
            return

        processed = 0
        failed = 0
        skipped = 0

        for paper in papers:
            try:
                self.stdout.write(f"Processing paper {paper.id}...", ending=" ")

                if not paper.file:
                    self.stdout.write(self.style.WARNING("✗ skipped (no PDF)"))
                    skipped += 1
                    continue

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
        self.stdout.write(f"Skipped: {skipped}")
        self.stdout.write("=" * 60)
