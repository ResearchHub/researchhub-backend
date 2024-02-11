from django.core.management.base import BaseCommand
from django.db.models import Q
from paper.models import Paper
from utils.openalex import OpenAlex
from paper.exceptions import DOINotFoundError
from dateutil.parser import parse

class Command(BaseCommand):
    help = 'Supplement paper with OpenAlex data if the discussion count is greater than 0'

    def handle(self, *args, **kwargs):
        papers = Paper.objects.filter(
            discussion_count__gt=0,
        )

        open_alex = OpenAlex()
        updated_papers = []
        total_papers_updated = 0
        batch_size = 10

        for paper in papers.iterator():
            if not paper.doi:
                continue  # Skip papers without a DOI

            try:
                openalex_work = open_alex.get_data_from_doi(paper.doi)
                data, _ = open_alex.parse_to_paper_format(openalex_work)

                needs_update = False
                if data.get("abstract") and not paper.abstract:
                    paper.abstract = data.get("abstract")
                    needs_update = True
                if data.get("pdf_license") and not paper.pdf_license:
                    paper.pdf_license = data.get("pdf_license")
                    needs_update = True
                if data.get("oa_status") and not paper.oa_status:
                    paper.oa_status = data.get("oa_status")
                    needs_update = True
                if data.get("is_open_access") and paper.is_open_access is None:
                    paper.is_open_access = data.get("is_open_access")
                    needs_update = True
                if data.get("open_alex_raw_json") and not paper.open_alex_raw_json:
                    paper.open_alex_raw_json = data.get("open_alex_raw_json")
                    needs_update = True
                if data.get("paper_publish_date") and not paper.paper_publish_date:
                    paper.paper_publish_date = parse(data.get("paper_publish_date")).date()
                    needs_update = True
                if data.get("alternate_ids") and not paper.alternate_ids:
                    paper.alternate_ids = data.get("alternate_ids")
                    needs_update = True

                # If this paper needs an update, add it to the list
                if needs_update:
                    updated_papers.append(paper)

                # When enough papers have been accumulated, update them in batch
                if len(updated_papers) >= batch_size:
                    Paper.objects.bulk_update(
                        updated_papers,
                        [
                            'abstract',
                            'pdf_license',
                            'oa_status',
                            'is_open_access',
                            'open_alex_raw_json',
                            'paper_publish_date',
                            'alternate_ids',
                        ],
                    )
                    total_papers_updated += len(updated_papers)
                    updated_papers = []  # Reset the list after updating

            except DOINotFoundError:
                continue

        if updated_papers:
            Paper.objects.bulk_update(
                updated_papers,
                [
                    'abstract',
                    'pdf_license',
                    'oa_status',
                    'is_open_access',
                    'open_alex_raw_json',
                    'paper_publish_date',
                    'alternate_ids',
                ],
            )
            total_papers_updated += len(updated_papers)

        self.stdout.write(self.style.SUCCESS(f'Batch update completed. Updated {total_papers_updated} papers.'))
