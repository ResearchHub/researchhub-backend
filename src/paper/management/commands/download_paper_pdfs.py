from django.core.management.base import BaseCommand
from django.db.models import Q

from paper.ingestion.constants import IngestionSource
from paper.models import Paper
from paper.tasks import download_pdf


class Command(BaseCommand):
    help = "Download PDFs for papers from a specific ingestion source"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            required=True,
            choices=[source.value for source in IngestionSource],
            help="Ingestion source to filter papers by",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be downloaded without actually queuing tasks",
        )

    def handle(self, *args, **options):
        source = options["source"]
        dry_run = options.get("dry_run", False)

        papers = (
            Paper.objects.filter(
                external_source=source,
                is_removed=False,
            )
            .filter(Q(file__isnull=True) | Q(file=""))
            .exclude(Q(pdf_url__isnull=True) | Q(pdf_url=""))
        ).order_by("created_date")

        total_count = papers.count()

        if total_count == 0:
            self.stdout.write(f"No papers found for source '{source}' without PDFs")
            return

        mode_text = "DRY RUN - " if dry_run else ""
        self.stdout.write(
            f"{mode_text}Found {total_count} papers from '{source}' without PDFs"
        )

        if dry_run:
            self.stdout.write("\nPapers that would be processed:\n")
            for i, paper in enumerate(papers.iterator()):
                self.stdout.write(f"{i+1}. Paper ID {paper.id}: {paper.pdf_url}")
            return  # exit dry run

        self.stdout.write("\nQueueing PDF download tasks...")

        success_count = 0
        error_count = 0

        for i, paper in enumerate(papers.iterator(), start=1):
            try:
                self.stdout.write(f"{i+1}. Paper ID {paper.id}: {paper.pdf_url}")
                download_pdf.apply_async((paper.id,), priority=5, countdown=0)
                success_count += 1

            except Exception as e:
                error_count += 1
                self.stdout.write(f"Failed to queue download for paper {paper.id}: {e}")

        # Summary
        self.stdout.write("\n" + "===\n")
        self.stdout.write(f"Successfully queued {success_count} PDF download tasks")
        if error_count > 0:
            self.stdout.write(f"Failed to queue {error_count} tasks")
        self.stdout.write("===\n")
