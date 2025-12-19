from dateutil import parser
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from paper.models import Figure, Paper
from paper.tasks import generate_thumbnail_for_figure


class Command(BaseCommand):
    help = "Generate thumbnails for primary figures that don't have one yet"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            nargs="*",
            help="Paper ID(s) to process (can specify multiple)",
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
            "--dry-run",
            action="store_true",
            help="Show what would be processed without actually generating thumbnails",
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

            papers = Paper.objects.filter(
                paper_publish_date__gte=published_start,
                paper_publish_date__lte=published_end,
            )
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
            )
            paper_ids = list(papers.values_list("id", flat=True))

        # Priority 3: Paper IDs (default) - if provided, filter by them
        # If not provided, process all papers with primary figures missing thumbnails
        if paper_ids:
            # Filter primary figures for specific papers
            primary_figures = Figure.objects.filter(
                paper_id__in=paper_ids,
                is_primary=True,
            ).filter(Q(thumbnail__isnull=True) | Q(thumbnail=""))
        else:
            # No paper IDs specified - process all primary figures without thumbnails
            primary_figures = Figure.objects.filter(
                is_primary=True,
            ).filter(Q(thumbnail__isnull=True) | Q(thumbnail=""))

        # Filter out figures without files
        primary_figures = primary_figures.filter(Q(file__isnull=False) & ~Q(file=""))

        if not primary_figures.exists():
            self.stdout.write(
                self.style.SUCCESS(
                    "No primary figures found without thumbnails. All done!"
                )
            )
            return

        self.stdout.write(
            f"\nFound {primary_figures.count()} primary figure(s) without thumbnails\n"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No thumbnails will be generated")
            )
            for fig in primary_figures[:20]:  # Show first 20
                try:
                    paper = fig.paper
                    self.stdout.write(
                        f"  Figure {fig.id}: {fig.file.name} "
                        f"(Paper {paper.id}: {paper.title[:50]}...)"
                    )
                except Exception as e:
                    self.stdout.write(f"  Figure {fig.id}: Error - {e}")
            if primary_figures.count() > 20:
                self.stdout.write(f"  ... and {primary_figures.count() - 20} more")
            return

        # Process figures
        self.stdout.write(f"Processing {primary_figures.count()} figure(s)...\n")
        processed = 0
        failed = 0
        skipped = 0

        for figure in primary_figures:
            try:
                paper = figure.paper
                self.stdout.write(
                    f"Figure {figure.id} (Paper {paper.id})...", ending=" "
                )

                # Double-check thumbnail doesn't exist (might have been created concurrently)
                figure.refresh_from_db()
                if figure.thumbnail:
                    self.stdout.write(
                        self.style.WARNING("✗ skipped (thumbnail already exists)")
                    )
                    skipped += 1
                    continue

                # Check if figure has a file
                if not figure.file:
                    self.stdout.write(self.style.WARNING("✗ skipped (no file)"))
                    skipped += 1
                    continue

                # Generate thumbnail
                success = generate_thumbnail_for_figure(figure)

                if success:
                    self.stdout.write(self.style.SUCCESS("✓ thumbnail created"))
                    processed += 1
                else:
                    self.stdout.write(self.style.ERROR("✗ failed"))
                    failed += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ error: {e}"))
                failed += 1

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Processed: {processed}")
        self.stdout.write(f"Failed: {failed}")
        self.stdout.write(f"Skipped: {skipped}")
        self.stdout.write("=" * 60)
