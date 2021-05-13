'''
Remove duplicated papers (same DOI)
'''
from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(doi__isnull=False)
        count = papers.count()
        print('Removing Duplicate Papers papers')
        for i, paper in enumerate(papers):
          print(f'Paper: {paper.id} - {i + 1}/{count}')
          same_doi = Paper.objects.filter(doi=paper.doi)
          if same_doi.count() > 1:
            same_doi.last().delete()
