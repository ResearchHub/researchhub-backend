"""
Management command to select primary images for multiple papers in batch.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from paper.models import Figure, Paper
from paper.tasks import select_primary_image


class Command(BaseCommand):
    help = "Select primary images for multiple papers in batch"

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
            help="Run selection asynchronously (via Celery)",
        )
        parser.add_argument(
            "--has-figures-only",
            action="store_true",
            help="Only process papers that have extracted figures",
        )
        parser.add_argument(
            "--no-primary-only",
            action="store_true",
            help="Only process papers that don't have a primary image yet",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-selection even if primary already exists",
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
        if options["has_figures_only"]:
            papers = papers.filter(figures__figure_type=Figure.FIGURE).distinct()

        if options["no_primary_only"]:
            papers = papers.exclude(figures__is_primary=True).distinct()

        # Apply limit
        papers = papers[: options["limit"]]

        paper_count = papers.count()

        if paper_count == 0:
            self.stdout.write(self.style.WARNING("No papers found to process"))
            return

        self.stdout.write(f"\nFound {paper_count} papers to process\n")

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No changes will be made\n")
            )
            for paper in papers:
                figures_count = Figure.objects.filter(
                    paper=paper, figure_type=Figure.FIGURE
                ).count()
                has_primary = (
                    "✓"
                    if Figure.objects.filter(paper=paper, is_primary=True).exists()
                    else "✗"
                )
                self.stdout.write(
                    f"  - Paper {paper.id}: {paper.title[:60]}... "
                    f"[Figures: {figures_count}, Primary: {has_primary}]"
                )
            return

        processed = 0
        failed = 0
        skipped = 0

        for paper in papers:
            try:
                self.stdout.write(
                    f"Processing paper {paper.id}...", ending=" "
                )

                figures = Figure.objects.filter(
                    paper=paper, figure_type=Figure.FIGURE
                )

                if not figures.exists():
                    self.stdout.write(
                        self.style.WARNING("✗ skipped (no figures)")
                    )
                    skipped += 1
                    continue

                # Check if primary already exists
                existing_primary = Figure.objects.filter(
                    paper=paper, is_primary=True
                ).first()
                if existing_primary and not options["force"]:
                    self.stdout.write(
                        self.style.WARNING(
                            f"✗ skipped (has primary: {existing_primary.file.name})"
                        )
                    )
                    skipped += 1
                    continue

                if options["async"]:
                    select_primary_image.apply_async((paper.id,), priority=5)
                    self.stdout.write(self.style.SUCCESS("queued"))
                else:
                    result = select_primary_image(paper.id)
                    if result:
                        primary = Figure.objects.filter(
                            paper=paper, is_primary=True
                        ).first()
                        if primary:
                            primary_type = (
                                "preview"
                                if primary.figure_type == Figure.PREVIEW
                                else "figure"
                            )
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"✓ (primary: {primary_type})"
                                )
                            )
                        else:
                            self.stdout.write(
                                self.style.WARNING("⚠ (no primary set)")
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

