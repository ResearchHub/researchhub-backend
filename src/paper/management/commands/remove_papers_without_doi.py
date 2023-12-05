"""
Remove papers without doi uploaded in the past 3 days
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from paper.models import Paper
from paper.tasks import censored_paper_cleanup
from researchhub_document.utils import reset_unified_document_cache


class Command(BaseCommand):
    def handle(self, *args, **options):
        three_days_ago = timezone.now().date() - timedelta(days=3)
        papers = Paper.objects.filter(
            doi__isnull=True, created_date__gte=three_days_ago, is_removed=False
        )
        count = papers.count()
        for i, paper in enumerate(papers):
            if paper.id == 832969:
                continue
            print(f"Paper: {paper.id} - {i + 1}/{count}")
            if not paper.doi:
                censored_paper_cleanup(paper.id)
        reset_unified_document_cache()
