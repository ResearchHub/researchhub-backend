'''
Remove papers without doi uploaded in the past 3 days
'''
from django.core.management.base import BaseCommand
from datetime import timedelta
from django.utils import timezone

from paper.models import Paper
from paper.tasks import censored_paper_cleanup
from paper.utils import reset_cache
from hub.models import Hub

class Command(BaseCommand):

    def handle(self, *args, **options):
        three_days_ago = timezone.now().date() - timedelta(days=3)
        papers = Paper.objects.filter(doi__isnull=True, uploaded_date__gte=three_days_ago, is_removed=False)
        count = papers.count()
        for i, paper in enumerate(papers):
            if paper.id == 832969:
                continue
            print(f'Paper: {paper.id} - {i + 1}/{count}')
            if not paper.doi:
                censored_paper_cleanup(paper.id)
        hub_ids = list(Hub.objects.filter(papers__in=list(papers.values_list(flat=True))).values_list(flat=True).distinct())
        print(hub_ids)
        reset_cache(hub_ids, {}, None)
