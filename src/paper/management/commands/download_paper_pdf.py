from dateutil import parser
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from paper.models import Paper
from paper.tasks import download_pdf


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--start_date", help="Perform for date starting")
        parser.add_argument("--end_date", help="End date")
        parser.add_argument(
            "--paper_id",
            nargs="+",
            type=int,
            help="Paper ID(s) to download PDF for (can specify multiple)",
        )

    def handle(self, *args, **options):
        paper_ids = options.get("paper_id")
        start_date = options.get("start_date")
        end_date = options.get("end_date")

        if paper_ids:
            # Download for specific paper IDs
            papers = Paper.objects.filter(id__in=paper_ids).filter(
                Q(file__isnull=True) | Q(file="")
            )
            self.stdout.write(f"Downloading PDFs for {papers.count()} paper(s)...")
        elif start_date and end_date:
            # Download for date range (existing functionality)
            start_date = parser.parse(start_date)
            end_date = parser.parse(end_date)
            self.stdout.write(f"Starting Date: {start_date}, End Date: {end_date}")
            papers = Paper.objects.filter(
                created_date__gte=start_date, created_date__lte=end_date
            ).filter(Q(file__isnull=True) | Q(file=""))
        else:
            raise CommandError(
                "Please provide either --paper_id or both --start_date and --end_date"
            )

        for i, paper in enumerate(papers.iterator()):
            self.stdout.write(
                f"Queuing download for paper {paper.id} ({i+1}/{papers.count()})"
            )
            download_pdf.apply_async((paper.id,), priority=9, countdown=2)
