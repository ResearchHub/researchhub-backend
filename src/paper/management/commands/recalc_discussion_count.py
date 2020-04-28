'''
Recalculates paper discussion count
'''
from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.iterator()
        count = Paper.objects.count()
        print('Recalculating paper discussion count')
        for i, paper in enumerate(papers):
            try:
                print(f'Paper: {paper.id} - {i + 1}/{count}')
                new_count = paper.get_discussion_count()
                paper.discussion_count = new_count
                paper.save()
            except Exception as e:
                print(
                    f'Error updating discussion count for paper: {paper.id}', e
                )

        print('Finished recalculating paper discussion count')
