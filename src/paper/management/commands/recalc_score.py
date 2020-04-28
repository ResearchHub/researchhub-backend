'''
Recalculates paper score
'''
from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.iterator()
        count = Paper.objects.count()
        print('Recalculating paper score')
        for i, paper in enumerate(papers):
            try:
                print(f'Paper: {paper.id} - {i + 1}/{count}')
                new_score = paper.calculate_score()
                paper.score = new_score
                paper.save()
            except Exception as e:
                print(f'Error updating score for paper: {paper.id}', e)

        print('Finished recalculating scores')
