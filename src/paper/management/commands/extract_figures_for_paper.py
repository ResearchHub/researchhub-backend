from django.core.management.base import BaseCommand, CommandError

from paper.models import Figure, Paper
from paper.tasks import extract_pdf_figures


class Command(BaseCommand):
    help = "Extract figures from PDF for a specific paper"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            nargs="*",
            help="Paper ID(s) to extract figures from (can specify multiple)",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run extraction asynchronously (via Celery)",
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

            for paper_id in paper_ids:
                try:
                    paper = Paper.objects.get(id=paper_id)
                    self.stdout.write(f"Paper {paper.id}...", ending=" ")

                    if not paper.file:
                        self.stdout.write(self.style.WARNING("✗ skipped (no PDF)"))
                        failed += 1
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
                except Paper.DoesNotExist:
                    self.stdout.write(self.style.ERROR("✗ not found"))
                    failed += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"✗ error: {e}"))
                    failed += 1

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(f"Processed: {processed}")
            self.stdout.write(f"Failed: {failed}")
            self.stdout.write("=" * 60)
            return

        # Single paper processing
        paper_id = paper_ids[0]

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f"Paper {paper_id} does not exist")

        self.stdout.write("\nExtracting figures for paper:")
        self.stdout.write(f"  ID: {paper.id}")
        self.stdout.write(f"  Title: {paper.title[:80]}...")
        self.stdout.write(f"  PDF File: {paper.file.name if paper.file else 'None'}\n")

        if not paper.file:
            raise CommandError("Paper has no PDF file. Cannot extract figures.")

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
            result = extract_pdf_figures(paper.id)

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
