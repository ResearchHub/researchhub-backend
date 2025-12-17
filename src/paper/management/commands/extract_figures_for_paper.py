from dateutil import parser
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from paper.models import Figure, Paper
from paper.tasks import extract_pdf_figures


class Command(BaseCommand):
    help = "Extract figures from PDF for papers"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            nargs="*",
            help="Paper ID(s) to extract figures from (can specify multiple)",
        )
        # Published date range (highest priority)
        parser.add_argument(
            "--published-start",
            help="Filter by published date starting from (paper_publish_date)",
        )
        parser.add_argument(
            "--published-end",
            help=(
                "Filter by published date ending at "
                "(defaults to today if --published-start is set)"
            ),
        )
        # Created date range (second priority)
        parser.add_argument(
            "--created-start",
            help="Filter by created date starting from",
        )
        parser.add_argument(
            "--created-end",
            help=(
                "Filter by created date ending at "
                "(defaults to today if --created-start is set)"
            ),
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run extraction asynchronously (via Celery)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without actually running extraction",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Process all papers even if they already have primary figures",
        )

    def handle(self, *args, **options):
        paper_ids = options["paper_id"]
        published_start = options.get("published_start")
        published_end = options.get("published_end")
        created_start = options.get("created_start")
        created_end = options.get("created_end")
        dry_run = options.get("dry_run", False)
        force = options.get("force", False)

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
            ).filter(
                (Q(file__isnull=False) & ~Q(file=""))
                | (Q(pdf_url__isnull=False) & ~Q(pdf_url=""))
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
            ).filter(
                (Q(file__isnull=False) & ~Q(file=""))
                | (Q(pdf_url__isnull=False) & ~Q(pdf_url=""))
            )
            paper_ids = list(papers.values_list("id", flat=True))

        # Priority 3: Paper IDs (default)
        if not paper_ids:
            raise CommandError(
                "Please provide paper IDs or use --published-start/--created-start"
            )

        # Filter out papers that already have primary figures (unless --force is used)
        if not force:
            papers_with_primary = set(
                Paper.objects.filter(
                    id__in=paper_ids,
                    figures__is_primary=True,
                ).values_list("id", flat=True)
            )

            skipped_count = len(papers_with_primary)
            paper_ids = [pid for pid in paper_ids if pid not in papers_with_primary]

            if skipped_count > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {skipped_count} paper(s) that already have "
                        f"primary figures (use --force to process them anyway)"
                    )
                )

        self.stdout.write(f"\nFound {len(paper_ids)} papers to process\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No extraction will occur"))
            for pid in paper_ids[:20]:  # Show first 20
                try:
                    paper = Paper.objects.get(id=pid)
                    has_primary = Figure.objects.filter(
                        paper=paper, is_primary=True
                    ).exists()
                    primary_status = " (has primary)" if has_primary else ""
                    self.stdout.write(
                        f"  {paper.id}: {paper.title[:60]}... "
                        f"(published: {paper.paper_publish_date}){primary_status}"
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

                    if not paper.file and not paper.pdf_url:
                        self.stdout.write(
                            self.style.WARNING("✗ skipped (no PDF file or pdf_url)")
                        )
                        failed += 1
                        continue

                    # Skip papers with primary figures unless --force is used
                    if not force:
                        has_primary = Figure.objects.filter(
                            paper=paper, is_primary=True
                        ).exists()
                        if has_primary:
                            self.stdout.write(
                                self.style.WARNING(
                                    "✗ skipped (already has primary figure)"
                                )
                            )
                            skipped += 1
                            continue

                    if options["async"]:
                        extract_pdf_figures.apply_async((paper.id,), priority=6)
                        self.stdout.write(self.style.SUCCESS("queued"))
                    else:
                        result = extract_pdf_figures(
                            paper.id, sync_primary_selection=True
                        )
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
                except Paper.DoesNotExist:
                    self.stdout.write(self.style.ERROR("✗ not found"))
                    failed += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"✗ error: {e}"))
                    failed += 1

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(f"Processed: {processed}")
            self.stdout.write(f"Skipped: {skipped}")
            self.stdout.write(f"Failed: {failed}")
            self.stdout.write("=" * 60)
            return

        # Single paper processing
        if not paper_ids:
            self.stdout.write(
                self.style.WARNING(
                    "No papers to process. All papers were skipped "
                    "(they already have primary figures or other filters "
                    "excluded them)."
                )
            )
            return

        paper_id = paper_ids[0]

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f"Paper {paper_id} does not exist")

        # Check if paper already has primary figure (unless --force is used)
        if not force:
            has_primary = Figure.objects.filter(paper=paper, is_primary=True).exists()
            if has_primary:
                raise CommandError(
                    f"Paper {paper_id} already has a primary figure. "
                    "Use --force to extract figures anyway."
                )

        self.stdout.write("\nExtracting figures for paper:")
        self.stdout.write(f"  ID: {paper.id}")
        self.stdout.write(f"  Title: {paper.title[:80]}...")
        self.stdout.write(f"  Published: {paper.paper_publish_date}")
        self.stdout.write(f"  PDF File: {paper.file.name if paper.file else 'None'}")
        self.stdout.write(f"  PDF URL: {paper.pdf_url if paper.pdf_url else 'None'}\n")

        if not paper.file and not paper.pdf_url:
            raise CommandError(
                "Paper has no PDF file or pdf_url. Cannot extract figures."
            )

        if options["async"]:
            self.stdout.write("Queuing extraction task...")
            extract_pdf_figures.apply_async((paper.id,), priority=6)
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ Extraction task queued. Check Celery logs for progress."
                )
            )
        else:
            self.stdout.write("Running extraction synchronously...")
            result = extract_pdf_figures(paper.id, sync_primary_selection=True)

            if result:
                figures = Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n✓ Successfully extracted {figures.count()} figures"
                    )
                )
                for fig in figures:
                    self.stdout.write(f"  - {fig.file.name}")
            else:
                raise CommandError("Extraction failed. Check logs for details.")
