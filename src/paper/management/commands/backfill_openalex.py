"""
Creates a wallet for users
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from paper.models import Paper
from utils.openalex import OpenAlex
from utils.sentry import log_info


class Command(BaseCommand):
    def handle(self, *args, **options):
        start_date = datetime.now() - timedelta(days=180)
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
                host_venue = result.get("host_venue", {})
                oa = result.get("open_access", {})

                paper.is_open_access = oa.get("is_oa", None)
                pdf_license = host_venue.get("license", None)
                pdf_license_url = host_venue.get("url", None)
                external_source = host_venue.get("display_name", None)

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
