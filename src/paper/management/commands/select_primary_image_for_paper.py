"""
Management command to select primary image for a paper using AWS Bedrock.
"""

from django.core.management.base import BaseCommand, CommandError

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

    def handle(self, *args, **options):
        paper_ids = options["paper_id"]

        if not paper_ids:
            raise CommandError("Please provide at least one paper ID")

        # Handle multiple papers
        if len(paper_ids) > 1:
            self.stdout.write(f"\nProcessing {len(paper_ids)} papers...\n")
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
