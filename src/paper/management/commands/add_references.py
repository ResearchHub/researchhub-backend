'''
Add or create references for all papers with doi and without reference.
'''
from django.core.management.base import BaseCommand

from paper.models import Paper
from paper.tasks import add_references


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(
            doi__isnull=False,
            is_public=True,
            references__isnull=True,
        )
        count = papers.count()
        for i, paper in enumerate(papers):
            print('{} / {}'.format(i, count))
            # If the paper has no references we are assuming it also has
            # no papers referencing it in the db yet.
            try:
                add_references(paper.id)
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to queue task for paper {paper.id}: {e}'
                ))