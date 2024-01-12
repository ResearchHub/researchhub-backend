"""
Creates a wallet for users
"""

from dateutil import parser
from django.core.management.base import BaseCommand

from paper.models import Paper
from utils.openalex import OpenAlex
from utils.sentry import log_info


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--start_date", help="Perform for date starting")

    def handle(self, *args, **options):
        start_date = parser.parse(options["start_date"])
        papers = Paper.objects.filter(
            created_date__gte=start_date, doi__icontains="10."
        )
        count = papers.count()
        open_alex = OpenAlex()
        for i, paper in enumerate(papers.iterator()):
            print(f"{i}/{count}")
            doi = paper.doi
            try:
                result = open_alex.get_data_from_doi(doi)
                primary_location = result.get("primary_location", {})
                oa = result.get("open_access", {})

                paper.is_open_access = oa.get("is_oa", None)
                pdf_license = primary_location.get("license", None)
                source = primary_location.get("source", None)
                if pdf_license is None:
                    pdf_license = result.get("license", None)
                pdf_license_url = pdf_license.get("url", None)
                external_source = source.get("display_name", None)

                if pdf_license:
                    paper.pdf_license = pdf_license
                if pdf_license_url:
                    paper.pdf_license_url = pdf_license_url
                if external_source:
                    paper.external_source = external_source
                paper.save()

            except Exception as e:
                print(e)
                log_info(e)
