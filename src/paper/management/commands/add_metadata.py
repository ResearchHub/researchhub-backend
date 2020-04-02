'''
Add metadata for all papers without a doi.
'''
from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(doi__isnull=True)
        count = papers.count()
        print('Adding metadata to papers')
        for i, paper in enumerate(papers):
            try:
                print(f'{i + 1}/{count}')
                paper.extract_meta_data()
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to queue task for paper {paper.id}: {e}'
                ))

        self.stdout.write(
            self.style.SUCCESS(f'Done adding metadata to papers')
        )
