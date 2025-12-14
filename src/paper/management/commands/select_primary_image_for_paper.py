"""
Management command to select primary image for a paper using AWS Bedrock.
"""

from dateutil import parser
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from paper.models import Figure, Paper
from paper.tasks import select_primary_image


class Command(BaseCommand):
    help = "Select primary image for a paper using AWS Bedrock"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            nargs="*",
            help="Paper ID(s) to select primary image for (can specify multiple)",
        )
        # Published date range (highest priority)
        parser.add_argument(
            "--published-start",
            help="Filter by published date starting from (paper_publish_date)",
        )
        parser.add_argument(
            "--published-end",
            help="Filter by published date ending at (defaults to today if --published-start is set)",
        )
        # Created date range (second priority)
        parser.add_argument(
            "--created-start",
            help="Filter by created date starting from",
        )
        parser.add_argument(
            "--created-end",
            help="Filter by created date ending at (defaults to today if --created-start is set)",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run selection asynchronously (via Celery)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-selection even if primary already exists",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without actually running selection",
        )

    def handle(self, *args, **options):
        paper_ids = options["paper_id"]
        published_start = options.get("published_start")
        published_end = options.get("published_end")
        created_start = options.get("created_start")
        created_end = options.get("created_end")
        dry_run = options.get("dry_run", False)

        # Priority 1: Published date range
        if published_start:
            published_start = parser.parse(published_start)
            if published_end:
                published_end = parser.parse(published_end)
            else:
                published_end = timezone.now()

            self.stdout.write(
                f"Filtering by PUBLISHED date: {published_start} to {published_end}"
            )

            # Only get papers that have extracted figures
            papers = Paper.objects.filter(
                paper_publish_date__gte=published_start,
                paper_publish_date__lte=published_end,
                figures__figure_type=Figure.FIGURE,
            ).distinct()
            paper_ids = list(papers.values_list("id", flat=True))

        # Priority 2: Created date range
        elif created_start:
            created_start = parser.parse(created_start)
            if created_end:
                created_end = parser.parse(created_end)
            else:
                created_end = timezone.now()

            self.stdout.write(
                f"Filtering by CREATED date: {created_start} to {created_end}"
            )

            papers = Paper.objects.filter(
                created_date__gte=created_start,
                created_date__lte=created_end,
                figures__figure_type=Figure.FIGURE,
            ).distinct()
            paper_ids = list(papers.values_list("id", flat=True))

        # Priority 3: Paper IDs (default)
        if not paper_ids:
            raise CommandError(
                "Please provide paper IDs or use --published-start/--created-start"
            )

        self.stdout.write(f"\nFound {len(paper_ids)} papers to process\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No selection will occur"))
            for pid in paper_ids[:20]:  # Show first 20
                try:
                    paper = Paper.objects.get(id=pid)
                    figures_count = Figure.objects.filter(
                        paper=paper, figure_type=Figure.FIGURE
                    ).count()
                    has_primary = Figure.objects.filter(
                        paper=paper, is_primary=True
                    ).exists()
                    self.stdout.write(
                        f"  {paper.id}: {figures_count} figures, "
                        f"primary={'yes' if has_primary else 'no'} "
                        f"(published: {paper.paper_publish_date})"
                    )
                except Paper.DoesNotExist:
                    self.stdout.write(f"  {pid}: NOT FOUND")
            if len(paper_ids) > 20:
                self.stdout.write(f"  ... and {len(paper_ids) - 20} more")
            return

        # Handle multiple papers
        if len(paper_ids) > 1:
            self.stdout.write(f"Processing {len(paper_ids)} papers...\n")
            processed = 0
            failed = 0
            skipped = 0

            for paper_id in paper_ids:
                try:
                    paper = Paper.objects.get(id=paper_id)
                    self.stdout.write(f"Paper {paper.id}...", ending=" ")

                    figures = Figure.objects.filter(
                        paper=paper, figure_type=Figure.FIGURE
                    )

                    if not figures.exists():
                        self.stdout.write(self.style.WARNING("✗ skipped (no figures)"))
                        skipped += 1
                        continue

                    existing_primary = Figure.objects.filter(
                        paper=paper, is_primary=True
                    ).first()
                    if existing_primary and not options["force"]:
                        self.stdout.write(self.style.WARNING("✗ skipped (has primary)"))
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
                                    self.style.SUCCESS(f"✓ (primary: {primary_type})")
                                )
                            else:
                                self.stdout.write(
                                    self.style.WARNING("⚠ (no primary set)")
                                )
                        else:
                            self.stdout.write(self.style.ERROR("✗ failed"))
                            failed += 1

                    processed += 1
                except Paper.DoesNotExist:
                    self.stdout.write(self.style.ERROR("✗ not found"))
                    failed += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"✗ error: {e}"))
                    failed += 1

            self.stdout.write("\n" + ("=" * 60))
            self.stdout.write(f"Processed: {processed}")
            self.stdout.write(f"Failed: {failed}")
            self.stdout.write(f"Skipped: {skipped}")
            self.stdout.write("=" * 60)
            return

        # Single paper processing
        paper_id = paper_ids[0]

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f"Paper {paper_id} does not exist")

        figures = Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE)

        if not figures.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Paper {paper_id} has no extracted figures. "
                    "Will create preview of first page instead."
                )
            )

        existing_primary = figures.filter(is_primary=True).first()
        if existing_primary and not options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Paper already has a primary image: {existing_primary.file.name}"
                )
            )
            self.stdout.write("Use --force to re-select")
            return

        self.stdout.write("\nSelecting primary image for paper:")
        self.stdout.write(f"  ID: {paper.id}")
        self.stdout.write(f"  Title: {paper.title[:80]}...")
        self.stdout.write(f"  Published: {paper.paper_publish_date}")
        self.stdout.write(f"  Available figures: {figures.count()}\n")

        for idx, fig in enumerate(figures):
            self.stdout.write(f"  {idx}. {fig.file.name}")

        if options["async"]:
            self.stdout.write("\nQueuing selection task...")
            select_primary_image.apply_async((paper.id,), priority=5)
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ Selection task queued. Check Celery logs for progress."
                )
            )
        else:
            self.stdout.write("\nRunning selection synchronously...")
            result = select_primary_image(paper.id)

            if result:
                # Check for primary (could be FIGURE or PREVIEW)
                primary = Figure.objects.filter(paper=paper, is_primary=True).first()
                if primary:
                    figure_type_label = (
                        "preview" if primary.figure_type == Figure.PREVIEW else "figure"
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"\n✓ Selected primary {figure_type_label}: "
                            f"{primary.file.name}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            "\n⚠ Selection completed but no primary was set"
                        )
                    )
            else:
                raise CommandError("Selection failed. Check logs for details.")
