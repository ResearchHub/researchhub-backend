'''
Add or create references for all papers with doi and without reference.
'''
from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(
            is_public=True,
            external_source='arxiv'
        )
        count = papers.count()
        for i, paper in enumerate(papers):
            print('Paper {} / {}'.format(i, count))
            paper.add_references()
