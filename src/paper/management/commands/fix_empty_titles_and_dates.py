from django.core.management.base import BaseCommand
from django.db.models import Q
from paper.models import Paper
from utils.openalex import OpenAlex
from paper.exceptions import DOINotFoundError
from dateutil.parser import parse

class Command(BaseCommand):
    help = 'Update paper titles and publication dates from OpenAlex for papers with NULL or empty titles'

    def handle(self, *args, **kwargs):
        papers = Paper.objects.filter(
            (Q(title__isnull=True) | Q(title='')) | Q(paper_publish_date__isnull=True),
            is_removed=False
        )

        open_alex = OpenAlex()
        updated_papers = []
        batch_size = 100

        for paper in papers.iterator():
            if not paper.doi:
                continue  # Skip papers without a DOI

            try:
                openalex_data = open_alex.get_data_from_doi(paper.doi)
                title = openalex_data.get('title')
                publication_date = openalex_data.get('publication_date')

                needs_update = False

                if title and not paper.title:
                    paper.title = title
                    needs_update = True

                if publication_date and not paper.paper_publish_date:
                    paper.paper_publish_date = parse(publication_date).date()
                    needs_update = True

                # If this paper needs an update, add it to the list
                if needs_update:
                    updated_papers.append(paper)

                # When enough papers have been accumulated, update them in batch
                if len(updated_papers) >= batch_size:
                    Paper.objects.bulk_update(updated_papers, ['title', 'paper_publish_date'])
                    updated_papers = []  # Reset the list after updating

            except DOINotFoundError:
                continue
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error updating paper {paper.id}: {str(e)}'))

        if updated_papers:
            Paper.objects.bulk_update(updated_papers, ['title', 'paper_publish_date'])

        self.stdout.write(self.style.SUCCESS('Batch update completed.'))
