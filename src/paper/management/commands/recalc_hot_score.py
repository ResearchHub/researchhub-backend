'''
Recalculates avg vote date
'''
from django.core.management.base import BaseCommand
from django.db.models import (
    Avg,
    IntegerField
)
from django.db.models.functions import Extract

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(vote__isnull=False).distinct('id').order_by('id')
        count = papers.count()
        print('Recalculating avg extract')
        for i, paper in enumerate(papers):
            try:
                print(f'Paper: {paper.id} - {i + 1}/{count}')
                paper.calculate_hot_score()

            except Exception as e:
                print(f'Error updating score for paper: {paper.id}', e)

        print('Finished recalculating avg extract')
