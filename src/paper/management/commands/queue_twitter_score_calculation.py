from django.core.management.base import BaseCommand
from paper.models import Paper
import os
from paper.tasks import celery_calculate_paper_twitter_score
import time

class Command(BaseCommand):

    def handle(self, *args, **options):
        today_papers = Paper.objects.filter(uploaded_date__gte='2021-04-09', twitter_score_updated_date__isnull=True)
        count = today_papers.count()
        for i, paper in enumerate(today_papers):
          success = celery_calculate_paper_twitter_score(paper.id)
          print('{} : {} / {}'.format(success, i, count))
          if not success:
            time.sleep(900)
            celery_calculate_paper_twitter_score(paper.id)
