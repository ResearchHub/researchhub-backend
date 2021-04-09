from django.core.management.base import BaseCommand
from paper.models import Paper
import os
from paper.tasks import celery_calculate_paper_twitter_score


class Command(BaseCommand):

    def handle(self, *args, **options):
        today_papers = Paper.objects.filter(uploaded_date__gte='4/9/21')
        for paper in today_papers:
            celery_calculate_paper_twitter_score(paper.id)
