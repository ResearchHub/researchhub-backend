from django.core.management.base import BaseCommand
from paper.models import Paper
import os
from paper.tasks import celery_calculate_paper_twitter_score


class Command(BaseCommand):

    def handle(self, *args, **options):
        today_papers = Paper.objects.filter(uploaded_date__gte='2021-04-09')
        count = today_papers.count()
        for i, paper in enumerate(today_papers):
          print('{} / {}'.format(i, count))
          celery_calculate_paper_twitter_score.apply_async(
              (paper.id,),
              priority=5,
              countdown=15
          )
