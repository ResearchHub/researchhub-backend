from dateutil import parser
from django.core.management.base import BaseCommand
from django.db.models import Q

from paper.models import Paper
from paper.tasks import download_pdf


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--start_date", help="Perform for date starting")
        parser.add_argument("--end_date", help="End date")

    def handle(self, *args, **options):
        start_date = parser.parse(options["start_date"])
        end_date = parser.parse(options["end_date"])
        print(f"Starting Date: {start_date}, End Date: {end_date}")

        papers = Paper.objects.filter(
            created_date__gte=start_date, created_date__lte=end_date
        ).filter(Q(file__isnull=True) | Q(file=""))

        for i, paper in enumerate(papers.iterator()):
            print(i)
            download_pdf.apply_async((paper.id,), priority=9, countdown=2)
