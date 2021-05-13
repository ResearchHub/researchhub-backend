'''
Take the abstract and make that a 255 version of a tagline
'''
from django.core.management.base import BaseCommand

from paper.models import Paper
from paper.tasks import add_references


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(abstract__isnull=False).exclude(abstract='')
        count = papers.count()
        for i, paper in enumerate(papers):
            print('{} / {}'.format(i, count))
            # If the paper has no references we are assuming it also has
            # no papers referencing it in the db yet.
            paper.tagline = paper.abstract[0:250] + '...'
            paper.save()
