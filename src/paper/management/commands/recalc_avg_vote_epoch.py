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
                new_score = paper.calculate_score()

                if new_score > 0:
                    ALGO_START_UNIX = 1588199677
                    vote_avg_epoch = paper.votes.aggregate(avg=Avg(Extract('created_date', 'epoch'), output_field=IntegerField()))['avg']
                    avg_hours_since_algo_start = (vote_avg_epoch - ALGO_START_UNIX) / 3600
                    hot_score = avg_hours_since_algo_start + new_score + paper.discussion_count * 2

                    paper.vote_avg_epoch = hot_score
                else:
                    paper.vote_avg_epoch = 0

                paper.save()
            except Exception as e:
                print(f'Error updating score for paper: {paper.id}', e)

        print('Finished recalculating avg extract')
