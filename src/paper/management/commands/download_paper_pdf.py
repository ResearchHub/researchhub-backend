from dateutil import parser
from django.core.management.base import BaseCommand
from django.db.models import Q

from paper.models import Paper
from paper.tasks import download_pdf


class Command(BaseCommand):
    help = "Download PDFs for papers. Can download for a specific paper ID or papers within a date range."

    def add_arguments(self, parser):
        parser.add_argument(
            "--paper_id",
            type=int,
            help="Download PDF for a specific paper by ID (overrides --start_date and --end_date)",
        )
        parser.add_argument("--start_date", help="Perform for date starting")
        parser.add_argument("--end_date", help="End date")
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously instead of queuing as async task (useful for testing)",
        )

    def handle(self, *args, **options):
        paper_id = options.get("paper_id")
        sync = options.get("sync", False)

        if paper_id:
            # Download for a specific paper
            try:
                paper = Paper.objects.get(id=paper_id)
                self.stdout.write(
                    f"Downloading PDF for paper {paper_id}: {paper.title}"
                )
                self.stdout.write(f"PDF URL: {paper.pdf_url or paper.url}")
                self.stdout.write(f"Current file: {paper.file or 'None'}")

                if sync:
                    result = download_pdf(paper_id)
                    if result:
                        paper.refresh_from_db()
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Successfully downloaded PDF. File path: {paper.file.name}"
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                "PDF download failed. Check logs for details."
                            )
                        )
                else:
                    download_pdf.apply_async((paper_id,), priority=9)
                    self.stdout.write(
                        self.style.SUCCESS(f"Queued PDF download for paper {paper_id}")
                    )

            except Paper.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Paper with ID {paper_id} not found")
                )
        else:
            # Download for papers in date range
            if not options.get("start_date") or not options.get("end_date"):
                self.stdout.write(
                    self.style.ERROR(
                        "Either --paper_id or both --start_date and --end_date must be provided"
                    )
                )
                return

            start_date = parser.parse(options["start_date"])
            end_date = parser.parse(options["end_date"])
            self.stdout.write(f"Starting Date: {start_date}, End Date: {end_date}")

            papers = Paper.objects.filter(
                created_date__gte=start_date, created_date__lte=end_date
            ).filter(Q(file__isnull=True) | Q(file=""))

            count = papers.count()
            self.stdout.write(f"Found {count} papers without PDFs")

            for i, paper in enumerate(papers.iterator(), 1):
                self.stdout.write(f"Processing {i}/{count}: Paper {paper.id}")
                if sync:
                    download_pdf(paper.id)
                else:
                    download_pdf.apply_async((paper.id,), priority=9, countdown=2)
